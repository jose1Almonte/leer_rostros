"""Tests del barrido bidireccional con un repo falso (sin DB ni pgvector)."""

from app.domain.matching import MatchingPolicy
from addon.matching_service import scan_matches


class FakeRepo:
    """Imita la interfaz que usa scan_matches, sin tocar la BD."""

    def __init__(self, buscadas, mejor_por_emb, ya_existentes=None):
        self._buscadas = buscadas
        self._mejor = mejor_por_emb  # dict: embedding -> mejor encontrada (o None)
        self._existentes = set(ya_existentes or [])  # set de (buscada, encontrada)
        self.registrados = []

    def buscadas_con_embedding(self, limite=0):
        return self._buscadas if not limite else self._buscadas[:limite]

    def mejor_encontrada(self, embedding):
        return self._mejor.get(embedding)

    def registrar_match(self, *, buscada_person_id, encontrada_person_id, **kw):
        par = (buscada_person_id, encontrada_person_id)
        if par in self._existentes:
            return None  # ON CONFLICT -> ya existía
        self._existentes.add(par)
        self.registrados.append(par)
        return f"id-{len(self.registrados)}"


def _enc(person_id, distancia, coincidencia=90):
    return {
        "person_id": person_id,
        "distancia": distancia,
        "coincidencia": coincidencia,
        "confianza": "alta",
    }


def test_registra_match_bajo_umbral():
    policy = MatchingPolicy(threshold=0.55)
    buscadas = [{"person_id": "B1", "telefono_contacto": "0412-1111111", "embedding": "e1"}]
    repo = FakeRepo(buscadas, {"e1": _enc("E1", 0.30)})

    resumen = scan_matches(repo, policy)

    assert resumen.matches_nuevos == 1
    assert resumen.buscadas_revisadas == 1
    assert ("B1", "E1") in repo.registrados


def test_ignora_distancia_sobre_umbral():
    policy = MatchingPolicy(threshold=0.55)
    buscadas = [{"person_id": "B1", "telefono_contacto": "0412-1111111", "embedding": "e1"}]
    repo = FakeRepo(buscadas, {"e1": _enc("E1", 0.80)})  # 0.80 >= 0.55 -> no match

    resumen = scan_matches(repo, policy)

    assert resumen.matches_nuevos == 0
    assert repo.registrados == []


def test_dedup_no_recuenta_existentes():
    policy = MatchingPolicy(threshold=0.55)
    buscadas = [{"person_id": "B1", "telefono_contacto": "0412-1111111", "embedding": "e1"}]
    repo = FakeRepo(buscadas, {"e1": _enc("E1", 0.20)}, ya_existentes={("B1", "E1")})

    resumen = scan_matches(repo, policy)

    assert resumen.matches_nuevos == 0
    assert resumen.matches_repetidos == 1


def test_marca_sin_telefono():
    policy = MatchingPolicy(threshold=0.55)
    buscadas = [{"person_id": "B1", "telefono_contacto": None, "embedding": "e1"}]
    repo = FakeRepo(buscadas, {"e1": _enc("E1", 0.20)})

    resumen = scan_matches(repo, policy)

    assert resumen.matches_nuevos == 1
    assert resumen.sin_telefono == 1


def test_sin_encontrada_no_registra():
    policy = MatchingPolicy(threshold=0.55)
    buscadas = [{"person_id": "B1", "telefono_contacto": "0412-1111111", "embedding": "e1"}]
    repo = FakeRepo(buscadas, {"e1": None})

    resumen = scan_matches(repo, policy)

    assert resumen.matches_nuevos == 0
    assert resumen.buscadas_revisadas == 1
