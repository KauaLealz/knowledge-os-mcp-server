"""Relógio naive em UTC e formato gravado no banco (sem o adaptador deprecado do sqlite3)."""

import warnings
from datetime import datetime, timedelta

from sqlalchemy import DateTime, bindparam, text

from knowledge_os.db.timeutil import utcnow


def test_utcnow_e_naive_e_proximo_do_utc():
    agora = utcnow()
    assert agora.tzinfo is None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        referencia = datetime.utcnow()
    assert abs(referencia - agora) < timedelta(seconds=5)


def test_parametro_datetime_em_sql_cru_grava_o_formato_de_sempre(test_engine):
    """O formato gravado por SQL cru tipado é o mesmo do ORM (`YYYY-MM-DD HH:MM:SS.ffffff`)."""
    valor = datetime(2026, 1, 2, 3, 4, 5, 6)
    with test_engine.begin() as conn:
        conn.execute(text("CREATE TABLE t_dt (a DATETIME)"))
        conn.execute(
            text("INSERT INTO t_dt (a) VALUES (:a)").bindparams(bindparam("a", type_=DateTime)),
            {"a": valor},
        )
        bruto = conn.execute(text("SELECT a FROM t_dt")).scalar()
        # Formato que o adaptador padrão do sqlite3 gravava antes (isoformat com espaço).
        assert bruto == valor.isoformat(" ")
        lido = conn.execute(select_dt()).scalar()
        assert lido == valor


def select_dt():
    return text("SELECT a FROM t_dt").columns(a=DateTime)
