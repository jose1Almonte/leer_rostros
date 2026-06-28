"""Barrido bidireccional: por cada BUSCADA, encontrar su mejor ENCONTRADA y
registrar el par como coincidencia si supera el umbral de MatchingPolicy.

No envía nada — solo detecta y persiste. El envío lo hace addon/cron.py."""

from dataclasses import dataclass

from app.domain.matching import MatchingPolicy

from addon.repository import MatchRepository


@dataclass
class ScanResumen:
    buscadas_revisadas: int = 0
    matches_nuevos: int = 0
    matches_repetidos: int = 0  # ya existían (ON CONFLICT)
    sin_telefono: int = 0


def scan_matches(
    repo: MatchRepository,
    policy: MatchingPolicy,
    *,
    limite: int = 0,
) -> ScanResumen:
    """Recorre las buscadas y registra coincidencias nuevas.

    `limite`: máximo de buscadas a procesar (0 = todas)."""
    resumen = ScanResumen()
    buscadas = repo.buscadas_con_embedding(limite=limite)
    for b in buscadas:
        resumen.buscadas_revisadas += 1
        mejor = repo.mejor_encontrada(b["embedding"])
        if not mejor or not policy.is_match(mejor["distancia"]):
            continue
        sin_tel = not (b["telefono_contacto"] and b["telefono_contacto"].strip())
        nuevo_id = repo.registrar_match(
            buscada_person_id=b["person_id"],
            encontrada_person_id=mejor["person_id"],
            distancia=mejor["distancia"],
            coincidencia=mejor["coincidencia"],
            confianza=mejor["confianza"],
            sin_telefono=sin_tel,
        )
        if nuevo_id is None:
            resumen.matches_repetidos += 1
        elif sin_tel:
            resumen.sin_telefono += 1
            resumen.matches_nuevos += 1
        else:
            resumen.matches_nuevos += 1
    return resumen
