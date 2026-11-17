"""CidadeViva MVP — backend único que liga Visão, IA de triagem, RPA e pipeline de dados."""
import csv
import hmac
import io
import logging
import os
import re
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from citizen_vision.service import ServiceError, extract_from_bytes

from . import db, geo, geocode, triagem

log = logging.getLogger("cidadeviva")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_FOTO = 8 * 1024 * 1024
UFS = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())

# Application Insights (Azure Monitor): liga sozinho se a connection string estiver configurada.
if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor()
        log.info("Application Insights ativo")
    except Exception as e:  # pacote ausente ou configuração inválida: o app segue sem telemetria
        log.warning("Application Insights não iniciou: %s", e)


# ---------- infra ----------
class Seguranca(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        t0 = time.time()
        resp = await call_next(request)
        resp.headers.update({
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin",
            "X-Frame-Options": "DENY", "Permissions-Policy": "camera=(self), geolocation=(self)",
            "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
        })
        log.info("%s %s %s %.0fms", request.method, request.url.path, resp.status_code, (time.time() - t0) * 1000)  # sem corpo, sem IP (LGPD)
        return resp


_JANELA = defaultdict(deque)


def limite(request: Request, nome: str, max_por_min: int):
    """Limite simples por IP (memória do processo): protege a IA e o OCR de abuso."""
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    q = _JANELA[(nome, ip)]
    agora = time.time()
    while q and agora - q[0] > 60:
        q.popleft()
    if len(q) >= max_por_min:
        return JSONResponse({"detail": "Muitas tentativas. Aguarde um minuto."}, status_code=429)
    q.append(agora)
    return None


def admin(request: Request):
    """Acesso por papel: operações da prefeitura/robô exigem ADMIN_KEY (nunca no código; vem do App Settings)."""
    chave = os.getenv("ADMIN_KEY", "")
    if not chave:
        return JSONResponse({"detail": "Administração desativada: ADMIN_KEY não configurada."}, status_code=503)
    dado = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(dado.encode(), chave.encode()):
        return JSONResponse({"detail": "Não autorizado."}, status_code=401)
    return None


def j(obj, status=200):
    return JSONResponse(obj, status_code=status)


# ---------- páginas ----------
async def pagina(request: Request):
    nome = {"/": "index.html", "/admin": "admin.html", "/painel": "painel.html"}[request.url.path]
    return FileResponse(STATIC / nome, headers={"Cache-Control": "no-cache"})


async def health(request: Request):
    return j({"status": "ok"})


# ---------- Visão ----------
async def extract_address(request: Request):
    if (r := limite(request, "ocr", 15)):
        return r
    form = await request.form()
    arq = form.get("file")
    if arq is None or not hasattr(arq, "read"):
        return j({"detail": "Envie a foto no campo 'file'."}, 400)
    dados = await arq.read()
    try:
        res = await run_in_threadpool(extract_from_bytes, dados, request.query_params.get("lookup_ibge") == "true")
    except ServiceError as e:
        return j({"detail": e.message}, e.status)
    return j(res)


# ---------- IA ----------
async def api_triagem(request: Request):
    if (r := limite(request, "ia", 20)):
        return r
    try:
        corpo = await request.json()
    except Exception:
        return j({"detail": "JSON inválido."}, 400)
    desc = str(corpo.get("descricao", "")).strip()
    if len(desc) < 8:
        return j({"detail": "Descreva o problema com um pouco mais de detalhe."}, 400)
    res = await run_in_threadpool(triagem.classificar, desc)
    cat = triagem.categorias().get(res["categoria"]) if res["categoria"] else None
    return j({**res, "categoria_nome": cat["nome"] if cat else None, "limiar": triagem.LIMIAR})


# ---------- preenchimento de endereço ----------
async def api_cep(request: Request):
    if (r := limite(request, "cep", 30)):
        return r
    cep = geocode.limpar_cep(request.path_params["cep"])
    if not cep:
        return j({"detail": "CEP deve ter 8 números."}, 400)
    res = await run_in_threadpool(geocode.viacep, cep)
    return j(res) if res else j({"detail": "CEP não encontrado."}, 404)


async def api_geocode(request: Request):
    if (r := limite(request, "geo", 15)):
        return r
    lat, lon = _num(request.query_params.get("lat")), _num(request.query_params.get("lon"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return j({"detail": "Coordenadas inválidas."}, 400)
    res = await run_in_threadpool(geocode.reverso, lat, lon)
    return j(res) if res else j({"detail": "Não foi possível descobrir o endereço."}, 404)


# ---------- reportes ----------
def _foto_segura(dados: bytes) -> bytes | None:
    """Decodifica e re-codifica a foto: valida que é imagem e remove EXIF (que pode trazer GPS e modelo do aparelho)."""
    img = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    k = min(1.0, 1600 / max(h, w))
    if k < 1:
        img = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None


def _num(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def _publico(r) -> dict:
    cat = triagem.categorias().get(r["categoria"], {})
    return {"codigo": r["codigo"], "status": r["status"], "categoria": r["categoria"], "categoria_nome": cat.get("nome"),
            "protocolo": r["protocolo"], "criado_em": r["created_at"], "requer_revisao": bool(r["requer_revisao"]),
            "local": ", ".join(x for x in [r["logradouro"], r["numero"], r["bairro"]] if x)}


async def criar_reporte(request: Request):
    if (r := limite(request, "reporte", 10)):
        return r
    f = await request.form()
    desc = str(f.get("descricao", "")).strip()
    if not 8 <= len(desc) <= 1500:
        return j({"detail": "A descrição deve ter entre 8 e 1500 caracteres."}, 400)
    logradouro = str(f.get("logradouro", "")).strip()[:120]
    lat, lon = _num(f.get("lat")), _num(f.get("lon"))
    if not logradouro and (lat is None or lon is None):
        return j({"detail": "Informe a rua ou use a sua localização."}, 400)
    uf = str(f.get("uf", "")).strip().upper()
    if uf and uf not in UFS:
        return j({"detail": "Estado inválido."}, 400)
    usuario = re.sub(r"[^a-zA-Z0-9-]", "", str(f.get("usuario_id", "")))[:40] or uuid.uuid4().hex

    ia = await run_in_threadpool(triagem.classificar, desc)  # recalculado no servidor: não confiamos no que o navegador diz
    escolhida = str(f.get("categoria", "")).strip()
    categoria = escolhida if escolhida in triagem.categorias() else ia["categoria"]
    if categoria is None:
        return j({"detail": "Escolha a categoria do problema."}, 400)
    revisao = ia["requer_revisao"]  # confiança baixa ou sem categoria => atendente confere antes do robô enviar

    foto_nome = None
    arq = f.get("foto")
    if arq is not None and hasattr(arq, "read"):
        bruto = await arq.read()
        if bruto:
            if len(bruto) > MAX_FOTO:
                return j({"detail": "Foto maior que 8 MB."}, 413)
            limpa = await run_in_threadpool(_foto_segura, bruto)
            if limpa is None:
                return j({"detail": "O arquivo enviado não é uma imagem válida."}, 400)
            foto_nome = uuid.uuid4().hex + ".jpg"
            (db.FOTOS / foto_nome).write_bytes(limpa)

    reg = db.inserir({
        "canal": "web", "descricao": desc, "texto_formal": ia["texto_formal"], "foto_arquivo": foto_nome,
        "logradouro": logradouro, "numero": str(f.get("numero", "")).strip()[:12], "bairro": str(f.get("bairro", "")).strip()[:80],
        "cidade": str(f.get("cidade", "")).strip()[:80], "uf": uf, "cep": str(f.get("cep", "")).strip()[:9],
        "endereco_origem": "foto_fatura" if f.get("origem_endereco") == "foto_fatura" else "manual",
        "subprefeitura": geo.subprefeitura(lat, lon), "lat": lat, "lon": lon,
        "ia_categoria": ia["categoria"], "ia_confianca": ia["confianca"], "ia_modelo": ia["modelo"],
        "categoria": categoria, "status": "novo" if revisao else "triado", "requer_revisao": int(revisao), "usuario_id": usuario,
    })
    log.info("reporte %s criado (categoria=%s, revisao=%s)", reg["codigo"], categoria, revisao)
    with db.conn() as c:
        row = c.execute("SELECT * FROM reporte WHERE id=?", (reg["id"],)).fetchone()
    return j(_publico(row), 201)


async def consultar(request: Request):
    with db.conn() as c:
        row = c.execute("SELECT * FROM reporte WHERE codigo=?", (request.path_params["codigo"].upper(),)).fetchone()
    return j(_publico(row)) if row else j({"detail": "Código não encontrado."}, 404)


async def foto(request: Request):
    nome = request.path_params["nome"]
    arq = db.FOTOS / nome
    if not re.fullmatch(r"[0-9a-f]{32}\.jpg", nome) or not arq.exists():
        return j({"detail": "não encontrado"}, 404)
    return FileResponse(arq, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ---------- administração (atendente) ----------
async def listar(request: Request):
    if (r := admin(request)):
        return r
    st = request.query_params.get("status")
    with db.conn() as c:
        rows = c.execute("SELECT * FROM reporte" + (" WHERE status=?" if st else "") + " ORDER BY created_at DESC LIMIT 200", (st,) if st else ()).fetchall()
    return j([{**_publico(r), "descricao": r["descricao"], "texto_formal": r["texto_formal"], "ia_categoria": r["ia_categoria"],
               "ia_confianca": r["ia_confianca"], "subprefeitura": r["subprefeitura"], "tem_foto": bool(r["foto_arquivo"]),
               "foto": f"/fotos/{r['foto_arquivo']}" if r["foto_arquivo"] else None, "erro_envio": r["erro_envio"]} for r in rows])


async def aprovar(request: Request):
    if (r := admin(request)):
        return r
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    with db.conn() as c:
        row = c.execute("SELECT * FROM reporte WHERE codigo=?", (request.path_params["codigo"].upper(),)).fetchone()
        if not row:
            return j({"detail": "Código não encontrado."}, 404)
        if row["status"] != "novo":
            return j({"detail": f"Reporte já está '{row['status']}'."}, 409)
        cat = corpo.get("categoria") or row["categoria"]
        if cat not in triagem.categorias():
            return j({"detail": "Categoria inválida."}, 400)
        c.execute("UPDATE reporte SET categoria=?, status='triado', requer_revisao=0 WHERE id=?", (cat, row["id"]))
    log.info("reporte %s aprovado por atendente (categoria=%s)", row["codigo"], cat)
    return j({"codigo": row["codigo"], "status": "triado", "categoria": cat})


async def export(request: Request):
    """Contrato lido pelo pipeline de dados (pipeline/ingest.py): GET /reportes/export?desde=AAAA-MM-DD&ate=AAAA-MM-DD."""
    if (r := admin(request)):
        return r
    desde, ate = request.query_params.get("desde", "0000-01-01"), request.query_params.get("ate", "9999-12-31")
    with db.conn() as c:
        rows = c.execute("SELECT * FROM reporte WHERE substr(created_at,1,10) BETWEEN ? AND ? ORDER BY created_at", (desde, ate)).fetchall()
    base = str(request.base_url).rstrip("/")
    return j([{
        "id": r["id"], "created_at": r["created_at"], "canal": r["canal"], "descricao": r["descricao"],
        "foto_url": f"{base}/fotos/{r['foto_arquivo']}" if r["foto_arquivo"] else None,
        "endereco": {"logradouro": r["logradouro"], "numero": r["numero"], "cep": r["cep"] or None,
                     "subprefeitura": r["subprefeitura"], "lat": r["lat"], "lon": r["lon"]},
        "ia": {"categoria": r["ia_categoria"], "confianca": r["ia_confianca"], "modelo": r["ia_modelo"]},
        "status": r["status"], "protocolo_prefeitura": r["protocolo"],
        "usuario": {"id": r["usuario_id"], "nome": None, "email": None},  # minimização: o app nem coleta nome/e-mail
    } for r in rows])


# ---------- ponte com o robô (UiPath lê/escreve CSV) ----------
CSV_COLS = ["id", "endereco", "categoria", "descricao", "foto", "status", "protocolo"]


async def rpa_fila(request: Request):
    if (r := admin(request)):
        return r
    with db.conn() as c:
        rows = c.execute("SELECT * FROM reporte WHERE status='triado' AND protocolo IS NULL ORDER BY created_at").fetchall()
    base = str(request.base_url).rstrip("/")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLS)
    for r in rows:
        end = ", ".join(x for x in [f"{r['logradouro']} {r['numero']}".strip(), r["bairro"], r["cidade"], r["uf"]] if x)
        w.writerow([r["codigo"], end, triagem.categorias()[r["categoria"]]["nome"], (r["texto_formal"] or r["descricao"]).replace("\n", " "),
                    f"{base}/fotos/{r['foto_arquivo']}" if r["foto_arquivo"] else "", "", ""])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="reclamacoes.csv"'})


async def rpa_resultado(request: Request):
    if (r := admin(request)):
        return r
    corpo = (await request.body()).decode("utf-8-sig", errors="replace")
    ok = falha = ignorados = 0
    with db.conn() as c:
        for lin in csv.DictReader(io.StringIO(corpo)):
            cod, st, prot = (lin.get("id") or "").strip().upper(), (lin.get("status") or "").strip().upper(), (lin.get("protocolo") or "").strip()
            row = c.execute("SELECT status FROM reporte WHERE codigo=?", (cod,)).fetchone()
            if not row or row["status"] != "triado":
                ignorados += 1
            elif st == "ENVIADO" and prot:
                c.execute("UPDATE reporte SET status='enviado_prefeitura', protocolo=?, erro_envio=NULL WHERE codigo=?", (prot, cod))
                ok += 1
            else:
                c.execute("UPDATE reporte SET erro_envio=? WHERE codigo=?", ("O portal rejeitou o envio; tratar manualmente.", cod))
                falha += 1
    log.info("resultado do RPA: %d enviados, %d falhas, %d ignorados", ok, falha, ignorados)
    return j({"enviados": ok, "falhas": falha, "ignorados": ignorados})


# ---------- painel ----------
async def stats(request: Request):
    with db.conn() as c:
        por_status = {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM reporte GROUP BY status")}
        por_cat = [{"categoria": r[0], "nome": triagem.categorias()[r[0]]["nome"], "total": r[1]}
                   for r in c.execute("SELECT categoria, COUNT(*) FROM reporte GROUP BY categoria ORDER BY 2 DESC")]
        total, revisao = c.execute("SELECT COUNT(*), COALESCE(SUM(requer_revisao),0) FROM reporte").fetchone()
    return j({"total": total, "por_status": por_status, "por_categoria": por_cat, "taxa_revisao_humana": round(revisao / total, 3) if total else None})


async def demanda(request: Request):
    """Demanda histórica real (SP156) vinda do Data Warehouse do pipeline de dados, se o arquivo estiver configurado em DW_PATH."""
    import sqlite3
    caminho = os.getenv("DW_PATH")
    if not caminho or not Path(caminho).exists():
        return j({"disponivel": False})
    try:
        c = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
        rows = c.execute("""SELECT s.nome_subprefeitura, d.nome, SUM(m.qtd_solicitacoes) AS total
                            FROM mart_demanda_subprefeitura_mes m JOIN dim_subprefeitura s USING (subprefeitura_id)
                            JOIN dim_categoria d USING (categoria_id) GROUP BY 1, 2 ORDER BY total DESC LIMIT 15""").fetchall()
        c.close()
    except Exception as e:
        log.warning("DW indisponível: %s", e)
        return j({"disponivel": False})
    return j({"disponivel": True, "fonte": "SP156 – Portal de Dados Abertos da PMSP (CC0)",
              "ranking": [{"subprefeitura": a, "categoria": b, "solicitacoes": int(t)} for a, b, t in rows]})


@asynccontextmanager
async def ciclo(app):
    db.init()
    yield


app = Starlette(
    routes=[
        Route("/", pagina), Route("/admin", pagina), Route("/painel", pagina), Route("/health", health),
        Route("/extract-address", extract_address, methods=["POST"]),
        Route("/api/triagem", api_triagem, methods=["POST"]),
        Route("/api/cep/{cep}", api_cep), Route("/api/geocode", api_geocode),
        Route("/api/reportes", criar_reporte, methods=["POST"]),
        Route("/api/reportes/{codigo}", consultar),
        Route("/api/admin/reportes", listar),
        Route("/api/admin/reportes/{codigo}/aprovar", aprovar, methods=["POST"]),
        Route("/reportes/export", export),
        Route("/rpa/fila.csv", rpa_fila),
        Route("/rpa/resultado", rpa_resultado, methods=["POST"]),
        Route("/api/stats", stats), Route("/api/demanda", demanda),
        Route("/fotos/{nome}", foto),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ],
    middleware=[Middleware(Seguranca)],
    lifespan=ciclo,
)
