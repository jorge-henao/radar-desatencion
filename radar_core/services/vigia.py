"""Vigía de Medios: señales curadas fuera del log de eventos.

Esta primera implementación evita acoplarse al proveedor LLM: recibe señales ya
estructuradas, aplica las reglas duras del Core y deja el punto de entrada listo
para que el grafo llame a estas mismas funciones.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Event, LocalidadPorIncorporar, SenalMedio, VigiaDocumento, VigiaRun
from ..schemas import Categoria
from .gazetteer import gazetteer

ESTADOS_VISIBLES = {"activa"}
CATEGORIAS_PROMPT = "agua|alimentos|medicamentos|aseo|techo|otro"


@dataclass(frozen=True)
class FuenteVigia:
    id: str
    url: str
    tipo: str = "medio"
    confianza: float = 0.8
    activa: bool = True

    @property
    def nombre(self) -> str:
        return self.id.replace("_", " ").title()


@dataclass(frozen=True)
class ConfigVigia:
    activo: bool = True
    cadencia_horas: int = 24
    caducidad_dias: int = 10
    modo: str = "curado"
    terminos_busqueda: tuple[str, ...] = ()
    fuentes: tuple[FuenteVigia, ...] = ()

    @property
    def fuentes_activas(self) -> tuple[FuenteVigia, ...]:
        return tuple(f for f in self.fuentes if f.activa)


@dataclass(frozen=True)
class LLMVigiaConfig:
    provider: str
    model: str
    api_key: str


class VigiaLLMError(RuntimeError):
    pass


def cargar_config(path: str | Path | None = None) -> ConfigVigia:
    """Lee el `vigia.yaml` simple del repo sin sumar una dependencia YAML.

    Soporta el subconjunto usado por la spec: escalares, listas de strings y
    bloques bajo `fuentes`. Si el archivo no existe, retorna defaults seguros.
    """
    ruta = Path(path or get_settings().vigia_config_path)
    if not ruta.exists():
        return ConfigVigia()
    data = _parse_yaml_simple(ruta.read_text())
    vigia = data.get("vigia", {})
    vista = data.get("vista_operativa", {})
    fuentes = tuple(
        FuenteVigia(
            id=str(f["id"]),
            url=str(f.get("url", "")),
            tipo=str(f.get("tipo", "medio")),
            confianza=float(f.get("confianza", 0.8)),
            activa=bool(f.get("activa", True)),
        )
        for f in vigia.get("fuentes", [])
        if f.get("id") and f.get("url")
    )
    return ConfigVigia(
        activo=bool(vigia.get("activo", True)),
        cadencia_horas=int(vigia.get("cadencia_horas", 24)),
        caducidad_dias=int(vigia.get("caducidad_dias", 10)),
        modo=str(vista.get("modo", "curado")),
        terminos_busqueda=tuple(str(t) for t in vigia.get("terminos_busqueda", [])),
        fuentes=fuentes,
    )


def ejecutar_vigia(
    session: Session,
    *,
    config: ConfigVigia | None = None,
    client: httpx.Client | None = None,
    llm_config: LLMVigiaConfig | None = None,
    forzar: bool = False,
) -> VigiaRun:
    """Ejecuta una pasada completa del Vigía con degradación por fuente.

    Pipeline: planificar fuentes activas -> recolectar -> extraer -> conciliar
    y persistir -> reportar. Las fallas quedan en el resumen y no abortan el
    barrido completo.
    """
    cfg = config or cargar_config()
    if not cfg.activo:
        return registrar_run(session, {"activo": False, "fuentes": {}}, estado="omitido")
    previa = ultima_pasada_ejecutada(session)
    ahora = dt.datetime.now(dt.UTC)
    if not forzar and previa is not None and ahora - previa < dt.timedelta(hours=cfg.cadencia_horas):
        return registrar_run(
            session,
            {
                "activo": True,
                "omitido_por_cadencia": True,
                "cadencia_horas": cfg.cadencia_horas,
                "ultima_pasada": previa.isoformat(),
            },
            estado="omitido",
        )

    resumen: dict[str, Any] = {
        "activo": True,
        "cadencia_horas": cfg.cadencia_horas,
        "fuentes": {},
        "procesadas": 0,
        "omitidas_por_hash": 0,
        "senales_extraidas": 0,
        "senales_persistidas": 0,
    }
    estado = "ok"
    propio = client is None
    http = client or httpx.Client(timeout=30)
    try:
        try:
            llm = llm_config or cargar_llm_config()
        except VigiaLLMError as exc:
            resumen["error"] = str(exc)
            return registrar_run(session, resumen, estado="parcial")

        for fuente in cfg.fuentes_activas:
            info = {"url": fuente.url, "senales": 0, "persistidas": 0}
            resumen["fuentes"][fuente.id] = info
            try:
                documento = leer_fuente(fuente, http)
                contenido_hash = hash_documento(fuente.url, documento)
                if documento_ya_procesado(session, fuente.url, contenido_hash):
                    info["omitida_por_hash"] = True
                    resumen["omitidas_por_hash"] += 1
                    continue
                senales = extraer_senales_llm(
                    documento,
                    url=fuente.url,
                    fuente=fuente,
                    llm_config=llm,
                    client=http,
                )
                info["senales"] = len(senales)
                resumen["senales_extraidas"] += len(senales)
                for senal in senales:
                    if registrar_senal(session, senal, fuente) is not None:
                        info["persistidas"] += 1
                        resumen["senales_persistidas"] += 1
                registrar_documento_procesado(session, fuente, contenido_hash)
                resumen["procesadas"] += 1
            except (httpx.HTTPError, VigiaLLMError, ValueError) as exc:
                info["error"] = str(exc)
                estado = "parcial"
        return registrar_run(session, resumen, estado=estado)
    finally:
        if propio:
            http.close()


def leer_fuente(fuente: FuenteVigia, client: httpx.Client) -> str:
    if not _url_verificable(fuente.url):
        raise ValueError("URL de fuente no verificable")
    resp = client.get(fuente.url)
    resp.raise_for_status()
    return resp.text


def documento_ya_procesado(session: Session, url: str, contenido_hash: str) -> bool:
    return (
        session.execute(
            select(VigiaDocumento.id).where(
                VigiaDocumento.url == url,
                VigiaDocumento.contenido_hash == contenido_hash,
            )
        ).first()
        is not None
    )


def registrar_documento_procesado(session: Session, fuente: FuenteVigia, contenido_hash: str) -> None:
    if documento_ya_procesado(session, fuente.url, contenido_hash):
        return
    session.add(VigiaDocumento(url=fuente.url, contenido_hash=contenido_hash, fuente_id=fuente.id))
    session.commit()


def cargar_llm_config() -> LLMVigiaConfig:
    settings = get_settings()
    provider = settings.vigia_llm_provider.strip().lower()
    if provider not in {"openai", "anthropic"}:
        raise VigiaLLMError("RADAR_VIGIA_LLM_PROVIDER debe ser 'openai' o 'anthropic'")
    api_key = settings.openai_api_key if provider == "openai" else settings.anthropic_api_key
    if not api_key:
        env = "RADAR_OPENAI_API_KEY" if provider == "openai" else "RADAR_ANTHROPIC_API_KEY"
        raise VigiaLLMError(f"Falta configurar {env}")
    if not settings.vigia_llm_model.strip():
        raise VigiaLLMError("Falta configurar RADAR_VIGIA_LLM_MODEL")
    return LLMVigiaConfig(provider=provider, model=settings.vigia_llm_model.strip(), api_key=api_key)


def extraer_senales_llm(
    documento: str,
    *,
    url: str,
    fuente: FuenteVigia,
    llm_config: LLMVigiaConfig | None = None,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Extrae señales estructuradas usando OpenAI o Anthropic según configuración.

    El resultado aún pasa por `registrar_senal`, que aplica las reglas duras:
    URL, categorías del enum, cita corta y conciliación contra gazetteer.
    """
    if not _url_verificable(url):
        return []
    cfg = llm_config or cargar_llm_config()
    prompt = _prompt_extraccion(documento, url=url, fuente=fuente)
    propio = client is None
    http = client or httpx.Client(timeout=60)
    try:
        try:
            if cfg.provider == "openai":
                texto = _llamar_openai(http, cfg, prompt)
            elif cfg.provider == "anthropic":
                texto = _llamar_anthropic(http, cfg, prompt)
            else:
                raise VigiaLLMError("Proveedor LLM no soportado")
        except httpx.HTTPStatusError as exc:
            raise VigiaLLMError(_detalle_error_http(cfg.provider, exc.response)) from exc
        except httpx.HTTPError as exc:
            raise VigiaLLMError(f"Fallo proveedor LLM {cfg.provider}") from exc
    finally:
        if propio:
            http.close()
    return _parse_senales_llm(texto, url=url, fuente=fuente)


def _prompt_extraccion(documento: str, *, url: str, fuente: FuenteVigia) -> str:
    return (
        "Extrae menciones de necesidad territorial para el Radar de Desatencion.\n"
        "Responde SOLO JSON valido con la forma {\"senales\":[...]}.\n"
        f"categorias permitidas: {CATEGORIAS_PROMPT}.\n"
        "Cada senal debe incluir localidad_texto, categorias, cita textual de maximo 40 palabras, "
        "fecha_publicacion si aparece y hogares_estimados solo si el texto lo dice explicitamente.\n"
        "No inventes cifras ni ubicaciones. Si no hay senales, usa {\"senales\":[]}.\n"
        f"fuente_id: {fuente.id}\nurl: {url}\n\nDocumento:\n{documento[:16000]}"
    )


def _llamar_openai(client: httpx.Client, cfg: LLMVigiaConfig, prompt: str) -> str:
    resp = client.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"},
        json={
            "model": cfg.model,
            "input": prompt,
            "text": {"format": _openai_senales_schema()},
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("output_text"):
        return str(data["output_text"])
    partes: list[str] = []
    for item in data.get("output", []):
        for contenido in item.get("content", []):
            if contenido.get("type") in {"output_text", "text"} and contenido.get("text"):
                partes.append(contenido["text"])
    return "\n".join(partes)


def _detalle_error_http(provider: str, response: httpx.Response) -> str:
    detalle = ""
    try:
        data = response.json()
    except ValueError:
        detalle = response.text[:240]
    else:
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            partes = [str(response.status_code)]
            if error.get("code"):
                partes.append(str(error["code"]))
            if error.get("message"):
                partes.append(str(error["message"])[:240])
            detalle = " · ".join(partes)
        else:
            detalle = str(data)[:240]
    return f"Fallo proveedor LLM {provider}: {detalle}"


def _openai_senales_schema() -> dict:
    return {
        "type": "json_schema",
        "name": "senales_vigia",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "senales": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "localidad_texto": {"type": "string"},
                            "categorias": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["agua", "alimentos", "medicamentos", "aseo", "techo", "otro"],
                                },
                            },
                            "urgencia_texto": {"type": "string"},
                            "cita": {"type": "string"},
                            "fecha_publicacion": {"type": ["string", "null"]},
                            "hogares_estimados": {"type": ["integer", "null"]},
                        },
                        "required": [
                            "localidad_texto",
                            "categorias",
                            "urgencia_texto",
                            "cita",
                            "fecha_publicacion",
                            "hogares_estimados",
                        ],
                    },
                }
            },
            "required": ["senales"],
        },
    }


def _llamar_anthropic(client: httpx.Client, cfg: LLMVigiaConfig, prompt: str) -> str:
    resp = client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": cfg.model,
            "max_tokens": 2048,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    partes = [c.get("text", "") for c in data.get("content", []) if c.get("type") == "text"]
    return "\n".join(partes)


def _parse_senales_llm(texto: str, *, url: str, fuente: FuenteVigia) -> list[dict]:
    try:
        data = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise VigiaLLMError("El proveedor LLM no devolvio JSON valido") from exc
    senales = data.get("senales", [])
    if not isinstance(senales, list):
        raise VigiaLLMError("El JSON del proveedor LLM no trae una lista 'senales'")
    normalizadas = []
    for s in senales:
        if not isinstance(s, dict):
            continue
        normalizadas.append({**s, "url": url, "fuente_id": fuente.id})
    return normalizadas


def _parse_yaml_simple(texto: str) -> dict[str, Any]:
    raiz: dict[str, Any] = {}
    seccion: str | None = None
    lista_actual: str | None = None
    item_actual: dict[str, Any] | None = None
    for cruda in texto.splitlines():
        linea = cruda.split("#", 1)[0].rstrip()
        if not linea.strip():
            continue
        indent = len(linea) - len(linea.lstrip(" "))
        limpia = linea.strip()
        if indent == 0 and limpia.endswith(":"):
            seccion = limpia[:-1]
            raiz.setdefault(seccion, {})
            lista_actual = None
            item_actual = None
            continue
        if seccion is None or ":" not in limpia and not limpia.startswith("- "):
            continue
        cont = raiz[seccion]
        if limpia.startswith("- "):
            valor = limpia[2:].strip()
            if ":" in valor:
                clave, bruto = valor.split(":", 1)
                item_actual = {clave.strip(): _yaml_val(bruto.strip())}
                cont.setdefault(lista_actual or "items", []).append(item_actual)
            elif lista_actual:
                cont.setdefault(lista_actual, []).append(_yaml_val(valor))
            continue
        clave, bruto = limpia.split(":", 1)
        clave = clave.strip()
        bruto = bruto.strip()
        if indent >= 4 and item_actual is not None:
            item_actual[clave] = _yaml_val(bruto)
        elif bruto == "":
            cont.setdefault(clave, [])
            lista_actual = clave
            item_actual = None
        else:
            cont[clave] = _yaml_val(bruto)
            lista_actual = None
            item_actual = None
    return raiz


def _yaml_val(valor: str) -> Any:
    v = valor.strip().strip('"').strip("'")
    if v.lower() in {"true", "false"}:
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def _url_verificable(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def registrar_senal(
    session: Session,
    senal: dict,
    fuente: FuenteVigia,
    *,
    detectada_at: dt.datetime | None = None,
) -> SenalMedio | None:
    """Valida, concilia y persiste una señal estructurada del Vigía.

    Señal sin URL o sin localidad no existe. Localidad sin pcode confiable se
    retiene para revisión y no entra en la tabla principal publicada.
    """
    url = str(senal.get("url") or "").strip()
    localidad = str(senal.get("localidad_texto") or "").strip()
    if not _url_verificable(url) or not localidad:
        return None
    categorias = _categorias_validas(senal.get("categorias") or [])
    if not categorias:
        categorias = ["otro"]
    cita = _cita_corta(str(senal.get("cita") or senal.get("urgencia_texto") or ""))
    if not cita:
        return None
    fecha_pub = _fecha(senal.get("fecha_publicacion") or senal.get("fecha_pub"))
    detectada = detectada_at or dt.datetime.now(dt.UTC)
    candidatos = gazetteer.buscar(localidad)
    pcode = _pcode_confiable(candidatos)
    if pcode is None:
        pendiente = session.execute(
            select(LocalidadPorIncorporar).where(
                LocalidadPorIncorporar.localidad_texto == localidad,
                LocalidadPorIncorporar.estado == "pendiente",
            )
        ).scalars().first()
        if pendiente is not None:
            return session.get(SenalMedio, pendiente.senal_id) if pendiente.senal_id else None
        retenida = None
        if candidatos:
            retenida = _crear_senal(
                session, senal, fuente, None, localidad, categorias, cita, url, fecha_pub, detectada, "revision"
            )
            session.flush()
        session.add(
            LocalidadPorIncorporar(
                senal_id=retenida.id if retenida else None,
                localidad_texto=localidad,
                candidatos=candidatos,
            )
        )
        session.commit()
        return retenida

    existente = _duplicada(session, pcode, categorias, fecha_pub, detectada)
    if existente is not None:
        existente.refuerzos += 1
        existente.fuentes = _sumar_fuente(existente.fuentes or [], fuente, url)
        session.commit()
        return existente

    estado = "convertida" if _existe_need_vigente(session, pcode) else "activa"
    nueva = _crear_senal(session, senal, fuente, pcode, localidad, categorias, cita, url, fecha_pub, detectada, estado)
    session.add(nueva)
    session.commit()
    return nueva


def _crear_senal(session, senal, fuente, pcode, localidad, categorias, cita, url, fecha_pub, detectada, estado):
    fuentes = _sumar_fuente([], fuente, url)
    return SenalMedio(
        pcode=pcode,
        localidad_texto=localidad,
        categorias=categorias,
        cita=cita,
        url=url,
        fuente_id=fuente.id,
        fuente_nombre=fuente.nombre,
        fuentes=fuentes,
        confianza=fuente.confianza,
        fecha_pub=fecha_pub,
        detectada_at=detectada,
        refuerzos=1,
        estado=estado,
    )


def _categorias_validas(valores) -> list[str]:
    permitidas = {c.value for c in Categoria}
    return sorted({str(v) for v in valores if str(v) in permitidas})


def _cita_corta(cita: str, max_palabras: int = 40) -> str:
    palabras = cita.strip().split()
    return " ".join(palabras[:max_palabras])


def _fecha(valor) -> dt.date | None:
    if isinstance(valor, dt.date):
        return valor
    if isinstance(valor, str) and valor:
        try:
            return dt.date.fromisoformat(valor[:10])
        except (TypeError, ValueError):
            return None
    return None


def _existe_need_vigente(session: Session, pcode: str) -> bool:
    folios_corregidos = select(Event.corrige_folio).where(Event.corrige_folio.is_not(None))
    return (
        session.execute(
            select(Event.id).where(
                Event.type == "need",
                Event.pcode == pcode,
                Event.folio.not_in(folios_corregidos),
            )
        ).first()
        is not None
    )


def _pcode_confiable(candidatos: list[dict]) -> str | None:
    if not candidatos:
        return None
    top = candidatos[0]
    if top["confianza"] < get_settings().umbral_confianza_geo:
        return None
    if len(candidatos) > 1 and top["confianza"] - candidatos[1]["confianza"] < 0.05:
        return None
    return top["pcode"]


def _duplicada(session: Session, pcode: str, categorias: list[str], fecha_pub, detectada) -> SenalMedio | None:
    corte = detectada - dt.timedelta(days=7)
    existentes = session.execute(
        select(SenalMedio).where(
            SenalMedio.pcode == pcode,
            SenalMedio.estado == "activa",
            SenalMedio.detectada_at >= corte,
        )
    ).scalars().all()
    cats = set(categorias)
    for e in existentes:
        if set(e.categorias or []) & cats:
            return e
    return None


def _sumar_fuente(actuales: list[dict], fuente: FuenteVigia, url: str) -> list[dict]:
    nuevo = {"id": fuente.id, "nombre": fuente.nombre, "url": url, "confianza": fuente.confianza}
    if not any(f.get("id") == fuente.id and f.get("url") == url for f in actuales):
        return [*actuales, nuevo]
    return actuales


def caducar_senales(session: Session, caducidad_dias: int, *, ahora: dt.datetime | None = None) -> int:
    limite = (ahora or dt.datetime.now(dt.UTC)) - dt.timedelta(days=caducidad_dias)
    senales = session.execute(
        select(SenalMedio).where(SenalMedio.estado == "activa", SenalMedio.detectada_at < limite)
    ).scalars().all()
    for senal in senales:
        senal.estado = "caducada"
    session.commit()
    return len(senales)


def convertir_senales_por_need(session: Session, pcode: str) -> int:
    senales = session.execute(
        select(SenalMedio).where(SenalMedio.pcode == pcode, SenalMedio.estado == "activa")
    ).scalars().all()
    for senal in senales:
        senal.estado = "convertida"
    return len(senales)


def descartar_senal(session: Session, senal_id, operador: str) -> bool:
    try:
        pk = senal_id if isinstance(senal_id, uuid.UUID) else uuid.UUID(str(senal_id))
    except ValueError:
        return False
    senal = session.get(SenalMedio, pk)
    if senal is None:
        return False
    senal.estado = "descartada"
    senal.descartada_por = operador
    session.commit()
    return True


def registrar_run(session: Session, resumen: dict, estado: str = "ok") -> VigiaRun:
    run = VigiaRun(
        estado=estado,
        resumen=resumen,
        finished_at=dt.datetime.now(dt.UTC),
    )
    session.add(run)
    session.commit()
    return run


def hash_documento(url: str, contenido: str) -> str:
    return hashlib.sha256(f"{url}\n{contenido}".encode()).hexdigest()


def ultima_pasada(session: Session) -> dt.datetime | None:
    run = session.execute(select(VigiaRun).order_by(VigiaRun.finished_at.desc().nulls_last())).scalars().first()
    return run.finished_at if run else None


def ultima_pasada_ejecutada(session: Session) -> dt.datetime | None:
    run = session.execute(
        select(VigiaRun)
        .where(VigiaRun.estado.in_(("ok", "parcial")))
        .order_by(VigiaRun.finished_at.desc().nulls_last())
    ).scalars().first()
    return run.finished_at if run else None
