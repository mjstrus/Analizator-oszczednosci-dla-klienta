from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from analyzer.parser import parse_jpk_fa

FIXTURES = Path(__file__).parent.parent / "fixtures"
NS = "http://crd.gov.pl/wzor/2021/11/29/11089/"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# Happy-path: kompletny plik JPK_FA
# ---------------------------------------------------------------------------

class TestParseJpkFa:
    def test_parsuje_wszystkie_faktury(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        assert len(docs) == 5

    def test_pola_pierwszej_faktury(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        first = docs[0]
        assert first.numer == "FV/001/2025/11"
        assert first.data == datetime(2025, 11, 5)
        assert first.nip_dostawcy == "9876543210"
        assert first.wartość == Decimal("15.00")
        assert first.typ == "KP"
        assert first.typ_płatności == "gotówka"

    def test_faktura_gotowkowa(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        doc = next(d for d in docs if d.numer == "FV/001/2025/11")
        assert doc.typ_płatności == "gotówka"

    def test_faktura_przelew(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        doc = next(d for d in docs if d.numer == "FV/002/2025/11")
        assert doc.typ_płatności == "przelew"
        assert doc.wartość == Decimal("5000.00")

    def test_korekta_ujemna_wartosc(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        kor = next(d for d in docs if d.numer == "KOR/001/2025/11")
        assert kor.wartość == Decimal("-200.00")
        assert kor.typ == "KD"

    def test_nota_typ_NT(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        nota = next(d for d in docs if d.numer == "NT/001/2025/11")
        assert nota.typ == "NT"

    def test_brak_nip_dostawcy_graceful(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        no_nip = next(d for d in docs if d.numer == "FV/003/2025/11")
        assert no_nip.nip_dostawcy == ""

    def test_id_sa_unikalne(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        ids = [d.id for d in docs]
        assert len(ids) == len(set(ids))

    def test_domyslny_status_new(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        assert all(d.status == "new" for d in docs)

    def test_domyslna_historia_pusta(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        assert all(d.historia == [] for d in docs)

    def test_domyslny_risk_level_none(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        assert all(d.risk_level is None for d in docs)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_uszkodzony_xml_zwraca_pusta_liste(self):
        result = parse_jpk_fa(b"<not valid xml <<")
        assert result == []

    def test_pusty_jpk_zwraca_pusta_liste(self):
        xml = (
            b'<?xml version="1.0"?>'
            b'<tns:JPK xmlns:tns="http://crd.gov.pl/wzor/2021/11/29/11089/"/>'
        )
        assert parse_jpk_fa(xml) == []

    def test_faktura_bez_nr_pomijana(self):
        xml = f"""<?xml version="1.0"?>
        <tns:JPK xmlns:tns="{NS}">
          <tns:Faktura>
            <tns:DataWystawienia>2025-11-01</tns:DataWystawienia>
            <tns:TypFaktury>VAT</tns:TypFaktury>
            <tns:P_15>100.00</tns:P_15>
          </tns:Faktura>
        </tns:JPK>""".encode()
        assert parse_jpk_fa(xml) == []

    def test_nieznany_typ_faktury_domyslnie_KP(self):
        xml = f"""<?xml version="1.0"?>
        <tns:JPK xmlns:tns="{NS}">
          <tns:Faktura>
            <tns:NrFaktury>TEST/001</tns:NrFaktury>
            <tns:DataWystawienia>2025-11-01</tns:DataWystawienia>
            <tns:TypFaktury>NIEZNANY</tns:TypFaktury>
            <tns:P_15>100.00</tns:P_15>
          </tns:Faktura>
        </tns:JPK>""".encode()
        docs = parse_jpk_fa(xml)
        assert len(docs) == 1
        assert docs[0].typ == "KP"

    def test_brak_sposobu_zaplaty_domyslnie_przelew(self):
        xml = f"""<?xml version="1.0"?>
        <tns:JPK xmlns:tns="{NS}">
          <tns:Faktura>
            <tns:NrFaktury>TEST/002</tns:NrFaktury>
            <tns:DataWystawienia>2025-11-01</tns:DataWystawienia>
            <tns:TypFaktury>VAT</tns:TypFaktury>
            <tns:P_15>500.00</tns:P_15>
          </tns:Faktura>
        </tns:JPK>""".encode()
        docs = parse_jpk_fa(xml)
        assert docs[0].typ_płatności == "przelew"

    def test_nip_z_myslnikami_sanitized(self):
        xml = f"""<?xml version="1.0"?>
        <tns:JPK xmlns:tns="{NS}">
          <tns:Faktura>
            <tns:NrFaktury>TEST/003</tns:NrFaktury>
            <tns:DataWystawienia>2025-11-01</tns:DataWystawienia>
            <tns:TypFaktury>VAT</tns:TypFaktury>
            <tns:P_15>100.00</tns:P_15>
            <tns:Podmiot2>
              <tns:DaneIdentyfikacyjne>
                <tns:NIP>987-654-32-10</tns:NIP>
              </tns:DaneIdentyfikacyjne>
            </tns:Podmiot2>
          </tns:Faktura>
        </tns:JPK>""".encode()
        docs = parse_jpk_fa(xml)
        assert docs[0].nip_dostawcy == "9876543210"

    def test_wartosc_z_przecinkiem_decimal(self):
        xml = f"""<?xml version="1.0"?>
        <tns:JPK xmlns:tns="{NS}">
          <tns:Faktura>
            <tns:NrFaktury>TEST/004</tns:NrFaktury>
            <tns:DataWystawienia>2025-11-01</tns:DataWystawienia>
            <tns:TypFaktury>VAT</tns:TypFaktury>
            <tns:P_15>1 234,56</tns:P_15>
          </tns:Faktura>
        </tns:JPK>""".encode()
        docs = parse_jpk_fa(xml)
        assert docs[0].wartość == Decimal("1234.56")

    def test_zla_data_uzywana_sentinel(self):
        xml = f"""<?xml version="1.0"?>
        <tns:JPK xmlns:tns="{NS}">
          <tns:Faktura>
            <tns:NrFaktury>TEST/005</tns:NrFaktury>
            <tns:DataWystawienia>not-a-date</tns:DataWystawienia>
            <tns:TypFaktury>VAT</tns:TypFaktury>
            <tns:P_15>100.00</tns:P_15>
          </tns:Faktura>
        </tns:JPK>""".encode()
        docs = parse_jpk_fa(xml)
        assert len(docs) == 1
        assert docs[0].data == datetime.min


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------

class TestDocumentModel:
    def test_dodaj_historię_zapisuje_zdarzenie(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        doc = docs[0]
        doc.dodaj_historię("test_event", {"key": "value"})
        assert len(doc.historia) == 1
        assert doc.historia[0]["zdarzenie"] == "test_event"
        assert doc.historia[0]["szczegóły"] == {"key": "value"}
        assert "timestamp" in doc.historia[0]

    def test_dodaj_historię_bez_szczegółów(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        doc = docs[0]
        doc.dodaj_historię("ocena_ryzyka")
        assert doc.historia[0]["szczegóły"] == {}

    def test_historia_niezależna_per_dokument(self):
        docs = parse_jpk_fa(fixture("sample_jpk_fa.xml"))
        docs[0].dodaj_historię("zdarzenie_A")
        assert docs[1].historia == []
