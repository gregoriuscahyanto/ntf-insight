"""Offline-Tests fuer 14-stellige Mercedes-Kurz-FIN ohne echte Fahrzeugdaten."""

from __future__ import annotations

import pytest

from ntf_insight.acquisition.fin_format import (
    fin_passt_zu_anfrage,
    ist_gueltige_fin,
)

KURZ = "1671061B000001"
VOLL = "W1N" + KURZ
VOLL_FREMD = "W1N1671061B000002"


def test_kurz_fin_opt_in_und_voll_fin_standard():
    assert len(KURZ) == 14
    assert len(VOLL) == 17
    assert ist_gueltige_fin(KURZ, kurz_erlaubt=True)
    assert not ist_gueltige_fin(KURZ)
    assert ist_gueltige_fin(VOLL)
    assert ist_gueltige_fin(VOLL, kurz_erlaubt=True)


@pytest.mark.parametrize("ungueltig", [
    "", "123", "123456789012345", "1234567890123456",
    "123456789012345678", "1671061B00000I", "1671061B00000O",
    "1671061B00000Q", "../1671061B000001", "1671061B0000*1",
])
def test_ungueltige_kennungen_werden_abgewiesen(ungueltig):
    assert not ist_gueltige_fin(ungueltig, kurz_erlaubt=True)


def test_kurz_fin_nur_exakt_oder_mit_17stelliger_wmi_ergaenzung():
    assert fin_passt_zu_anfrage(KURZ, KURZ)
    assert fin_passt_zu_anfrage(KURZ, VOLL)
    assert fin_passt_zu_anfrage(KURZ, "w1n-" + KURZ.lower())
    assert not fin_passt_zu_anfrage(KURZ, VOLL_FREMD)
    assert not fin_passt_zu_anfrage(VOLL, KURZ)  # Kein Verkuerzen einer Voll-FIN
    assert fin_passt_zu_anfrage(VOLL, VOLL)
    assert not fin_passt_zu_anfrage(KURZ, "XX" + KURZ)
