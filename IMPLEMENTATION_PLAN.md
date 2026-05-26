---
date: 2026-05-26
topic: analyzer-oszczednosci-mvp
status: ready_for_implementation
---

# Dev Plan: Analyzer Oszczędności Dokumentów
## MVP Implementation Plan

**Dokument źródłowy:** `/home/claude/analyzer-oszczednosci-comprehensive-requirements.md`

---

## Problem & Scope

System będzie analizować dokumenty księgowe (JPK_FA XML) i sugerować klientom **konkretne scenariusze optymalizacji** kosztów księgowania poprzez:
- **Pomijanie** dokumentów o niskiej wartości
- **Zbiorcze faktury** (sugestia dla dostawcy)
- **Przesunięcia** dokumentów do następnego miesiąca

To MVP pokrywa **jednostanowiskowe wdrażanie w Streamlit** z persistence w JSON.

**Non-goals:** Pełna integracja Frappe CRM (Phase 2), WAlidacja JPK_FA vs MF API (docelowo), wszystkie formy działalności (KPIR/KSH/Ryczałt VAT na start).

---

## Wymagania kluczowe (z źródła)

- **R1-R6:** Parser JPK_FA + Tax Advisor Agent + Rule Engine
- **R7:** Impact prognozowania (przesunięcia wpływają na kolejny miesiąc)
- **R8-R10:** Output PDF + JSON, handoff do księgowej
- **R13-R15:** TOP 5 wariantów z rankingiem, tylko rekomendacje, brak automatyki

---

## Kryteria sukcesu

- ✅ Parser poprawnie ekstrahuje dokumenty z JPK_FA XML
- ✅ Tax Advisor ocenia RISK_LEVEL (LOW/MED/HIGH) dla każdego dokumentu
- ✅ Generuje TOP 5 wariantów z kombinacjami akcji
- ✅ Oszczędności są matematycznie poprawne
- ✅ Decyzje klienta pamiętane w dzienniku reguł
- ✅ PDF jest actionable (checkboxy, jasne instrukcje)
- ✅ System uczy się preferencji klienta (compatibility score)

---

## Kontekst repo i wzorce

### Istniejące wzorce do naśladowania

1. **JPK_FA Parsing:**
   - `ift2r-generator` (repo) – już parsuje JPK_FA XML
   - `raport-kasowy` – ekstrahuje dane z JPK_FA do XLSX
   - Struktura: `InvoiceItem = {numer, data, nip_dostawcy, wartość, typ}`

2. **Streamlit patterns:**
   - `informacja-dodatkowa` – sidebar z config, session_state, PDF export via ReportLab
   - `polityka-rachunkowosci` – wieloetapowy wizard
   - `Symphony year-end auditor` – Streamlit UI z tabelami i charts

3. **PDF generation:**
   - `raport-kasowy` – ReportLab + DejaVuSans.ttf dla polskich znaków
   - `polityka-rachunkowosci` – XLSX export + PDF

4. **JSON persistence:**
   - Wzorzec: `config.json` / `rules.json` w root
   - Session state + file-based storage

### Guidance z CLAUDE.md

- Preferuj Streamlit Cloud deployment
- Użyj GitHub do versionowania
- SQL/Supabase tylko gdy rzeczywiście potrzebny (MVP może być JSON)

---

## Kluczowe decyzje techniczne

### D1: Architektura modułowa
- **Parser:** `analyzer/parser.py` – ekstrahuje JPK_FA XML → lista `Document` objects
- **Tax Advisor:** `analyzer/tax_advisor.py` – ocenia RISK_LEVEL per dokument
- **Rule Engine:** `analyzer/rules.py` – ładuje/zapisuje dziennik reguł (JSON)
- **Search/Ranker:** `analyzer/optimizer.py` – generuje warianty + rankinguje
- **Output:** `analyzer/output.py` – generuje PDF + JSON
- **Streamlit UI:** `app.py` – orchestrujący wszystko

**Uzasadnienie:** Łatwa testowalna architektura, każdy moduł odpowiada za jedną odpowiedzialność.

### D2: Model dokumentu – dataclass
```python
@dataclass
class Document:
    id: str  # unique ID z JPK_FA
    numer: str
    data: datetime
    nip_dostawcy: str
    wartość: Decimal
    typ: str  # KP, NT, KD
    typ_płatności: str  # gotówka / przelew
    risk_level: str = None  # LOW/MED/HIGH (set by Tax Advisor)
    status: str = "new"  # new, risk_assessed, in_variant_X, selected, confirmed, executed
    historia: List[Dict] = field(default_factory=list)
```

**Uzasadnienie:** Type-safe, łatwe serializować do JSON, historia zmian wbudowana.

### D3: Rule Engine – JSON z meta
```json
{
  "klient_id": "XYZ",
  "rules": [
    {
      "id": "r001",
      "typ": "system" | "client_preference",
      "forma": "KPIR",
      "warunki": {"wartość": {"min": null, "max": 50}},
      "działanie": "sugeruj_pomijanie",
      "priorytet": 1,
      "liczba_zastosowań": 0
    }
  ]
}
```

**Uzasadnienie:** Łatwo edytowalny, queryable, extensible. `liczba_zastosowań` da nam feedback na temat skuteczności reguł.

### D4: Wariant – kombinacja akcji
```python
@dataclass
class Variant:
    id: int  # 1-5
    oszczędność: Decimal  # nowa_cena - stara_cena
    dokumenty_do_pomijania: List[Document]
    grupy_do_zbiorczenia: List[Tuple[str, List[Document]]]  # (dostawca, dokumenty)
    dokumenty_do_przesunięcia: List[Tuple[Document, str]]  # (dokument, target_month)
    risk_level: str  # MAX ze wszystkich dokumentów
    compatibility_score: float  # 0-1, oparte na historii klienta
```

**Uzasadnienie:** Atomarna jednostka decyzji, łatwa do serializacji i komunikacji.

### D5: PDF generation – ReportLab
- Używaj `reportlab` + `reportlab-style-utils` (jeśli dostępne)
- Polski tekst: DejaVuSans.ttf (jak w `raport-kasowy`)
- Struktura: header (dane klienta), TOP 5 wariantów (każdy to sekcja), checkboxy dla księgowej

**Uzasadnienie:** Deterministyczne, kontrolowalne, dobrze się integruje z Streamlit.

### D6: Ranking wariantów – weighted scoring
```
score = (
  oszczędność_normalized * 0.5 +  # 50% waga na oszczędność
  compatibility_score * 0.3 +      # 30% match z historią
  (1 - risk_level_value) * 0.2     # 20% bezpieczeństwo (LOW=1, MED=0.5, HIGH=0)
)
```

**Uzasadnienie:** Zarówno finansowe jak i personalne preferencje + bezpieczeństwo.

---

## Otwarte pytania

### Rozwiązane podczas planowania

- **Jak parsować JPK_FA?** → Użyj `lxml` + pattern z `ift2r-generator`
- **Gdzie przechowywać reguły?** → JSON `rules/{klient_id}.json`
- **Jak rankingować?** → Weighted scoring (patrz D6)

### Odroczone do implementacji

- **[Wymaga researchu]** Dokładna struktura namespace'ów w JPK_FA v1.3+ (sprawdzić najnowszy XSD)
- **[Techniczne]** Czy Streamlit cached functions wystarczą do perfor performance, czy trzeba będzie Pandas optimization?
- **[Wymaga researchu]** Jaka dokładnie struktura XSD dla KP/NT/KD elementów
- **[Techniczne]** Czy ReportLab pagination automatyczne czy trzeba ręczne?

---

## Implementation Units

### ✅ Unit 1: JPK_FA Parser

**Cel:** Ekstrakcja dokumentów z JPK_FA XML → lista `Document` objects

**Wymagania:** R1

**Zależności:** Brak

**Pliki:**
- Stwórz: `analyzer/parser.py`
- Stwórz: `analyzer/models.py` (Document dataclass)
- Test: `tests/test_parser.py`

**Podejście:**
- Użyj `lxml.etree` do parsowania XML
- Pattern: Z `ift2r-generator` – namespace handling
- Ekstrahuj: numer, data, NIP dostawcy, wartość (ze wszystkich walut), typ, typ_płatności
- Error handling: Jeśli XML jest malformed, log do stderr + continue (nie fail na całym pliku)
- Walidacja: Basic checks – data powinni być valid, NIP powinien być numerem

**Wzorce do naśladowania:**
- `ift2r-generator/main.py` – JPK_FA parsing
- `raport-kasowy/parsers/jpk_fa_parser.py` – typ_płatności extraction

**Scenariusze testowe:**
- ✅ Prawidłowy JPK_FA XML z 10 dokumentami → ekstrahuje 10 Document objects
- ✅ Dokument z NIP zawierającym znaki non-numeric → handle gracefully
- ✅ Dokument bez NIP dostawcy → NIP="" lub error?
- ✅ Dokument z negatywną wartością (korekta) → ekstrahuje prawidłowo
- ✅ Pusta lista dokumentów → zwraca pustą listę

**Weryfikacja:**
- Parser extrahuje co najmniej 90% dokumentów z testowego JPK_FA
- Każdy Document ma wszystkie atrybuty non-None
- Data jest `datetime` object

---

### ✅ Unit 2: Tax Advisor Agent

**Cel:** Ocena RISK_LEVEL (LOW/MED/HIGH) dla każdego dokumentu

**Wymagania:** R3, R4

**Zależności:** Unit 1 (Parser), Rule Engine (Unit 3)

**Pliki:**
- Stwórz: `analyzer/tax_advisor.py`
- Stwórz: `analyzer/risk_rules.json` (system rules dla RISK_LEVEL)
- Test: `tests/test_tax_advisor.py`

**Podejście:**
- Każdy Document przechodzi przez serię pytań:
  1. Czy typ_płatności = "przelew" w KSH? → MEDIUM/HIGH
  2. Czy wartość < 50 w KPIR? → LOW
  3. Czy typ = "NT" (nota)? → LOW (elastyczne)
  4. Czy typ = "KP" z wysoką wartością? → MEDIUM
  5. Szukaj w dzienniku reguł czy jest explicit rule dla tego dokumentu
- Output: Każdy Document.risk_level = "LOW" | "MED" | "HIGH"
- Log: Dla każdego dokumentu, zapamiętaj dlaczego ocenę (powód)

**Wzorce do naśladowania:**
- Brak bezpośredniego precedensu w repo – to nowy moduł
- Inspiracja: `informacja-dodatkowa/validators.py` – conditional logic

**Scenariusze testowe:**
- ✅ KPIR + gotówka + 15 zł → LOW
- ✅ KPIR + przelew + 5000 zł → MEDIUM (duża wartość, ale KPIR ok)
- ✅ KSH + przelew + dowolna wartość → HIGH (przelewy w KSH są fixed)
- ✅ Dokument z custom rule "zawsze BAIXO" → LOW
- ✅ NT (nota) → zawsze LOW niezależnie od formy

**Weryfikacja:**
- Każdy dokument ma risk_level
- Historia zmian (powód oceny) jest zapisana w Document.historia

---

### ✅ Unit 3: Rule Engine

**Cel:** Zarządzanie dziennika reguł (system + client preferences)

**Wymagania:** R4, R9

**Zależności:** Brak (niezalezny moduł)

**Pliki:**
- Stwórz: `analyzer/rules.py`
- Stwórz: `data/rules_system.json` (default system rules)
- Stwórz: `data/rules_klient_{id}_template.json` (template dla nowego klienta)
- Test: `tests/test_rules.py`

**Podejście:**
- Ładuj `data/rules_klient_{klient_id}.json` (jeśli istnieje) + `data/rules_system.json`
- Merge: System rules + client rules (client rules override system jeśli konflikt)
- Query: Dla dokumentu X, jaka reguła pasuje?
- Add rule: Zapisz nową rule do JSON (ze source = "client_preference")
- Track: `liczba_zastosowań` – ile razy ta reguła była użyta

**Wzorce do naśladowania:**
- `polityka-rachunkowosci/config_loader.py` – JSON config handling
- Standard: `dict` + `json.load/dump`

**Scenariusze testowe:**
- ✅ Load system rules + client rules → merge bez konfliktów
- ✅ Query: dokument KPIR + 30 zł → zwraca rule "sugeruj_pomijanie"
- ✅ Add rule: nowa client preference → zapisuje do JSON
- ✅ Conflict: system rule + client rule → client wins
- ✅ Empty rules → zwraca pusty dict (no rules = default behavior)

**Weryfikacja:**
- Rules się ładują prawidłowo z JSON
- Query zwraca sensowne reguły dla dokumentów
- New rules są persistowane w JSON

---

### ✅ Unit 4: Constraint Definition (Tax Advisor + Rules)

**Cel:** Zidentyfikowanie dokumentów NO-GO (nie można ruszać)

**Wymagania:** R5 (constraint-based algorytm)

**Zależności:** Unit 2 (Tax Advisor), Unit 3 (Rule Engine)

**Pliki:**
- Stwórz: `analyzer/constraints.py`
- Test: `tests/test_constraints.py`

**Podejście:**
- Input: Lista dokumentów (każdy ma risk_level)
- Logic: Dokumenty HIGH RISK lub z rule "nie_można_ruszać" → NO-GO
- Output: 
  - `no_go_documents` – dokumenty które nie będzie rozpatrywać
  - `remaining_set` – dokumenty do optymalizacji
- Logging: Dla każdego NO-GO dokumentu, powód

**Wzorce do naśladowania:**
- Brak precedensu – nowa logika

**Scenariusze testowe:**
- ✅ Wszystkie dokumenty LOW RISK → remaining_set = wszystkie
- ✅ 1 HIGH RISK, reszta LOW → no_go zawiera 1, remaining_set zawiera resztę
- ✅ Rule "nie_można_ruszać" → dokument w no_go niezależnie od risk_level
- ✅ KSH + przelew → zawsze no_go

**Weryfikacja:**
- no_go_documents + remaining_set = wszystkie dokumenty
- Brak dokumentu HIGH RISK w remaining_set

---

### ✅ Unit 5: Variant Generator (Search)

**Cel:** Generowanie ~50-100 wariantów (kombinacje pomijania, zbiorczych, przesunięć)

**Wymagania:** R6

**Zależności:** Unit 4 (Constraints), Unit 3 (Rules)

**Pliki:**
- Stwórz: `analyzer/optimizer.py`
- Test: `tests/test_optimizer.py`

**Podejście:**
- Input: `remaining_set` dokumentów, target próg ilościowy
- Search strategy: **Ambitna (B)** – kombinacje kombinacji
  - Generuj pojedyncze akcje:
    - Każdy podzbiór do pomijania (size 1, 2, 3, ...)
    - Każdy grupa do zbiorczenia (każdy dostawca osobno)
    - Każdy dokument do przesunięcia (każdy miesiąc)
  - Kombinuj: pomijanie + zbiorcze, pomijanie + przesunięcie, itd.
- Filtering: 
  - Zachowaj tylko warianty które mają oszczędności > 0
  - Deduplikuj (jeśli wariant A i B dają ten sam rezultat, keep tylko jeden)
  - Limit: Top 50-100 wariantów (przed rankingiem)
- Dla każdego wariantu:
  - Licz nową ilość dokumentów
  - Licz nową cenie (lookup w cenniku)
  - Oblicz oszczędność
  - Assign risk_level = MAX(risk levels dokumentów w wariancie)

**Wzorce do naśladowania:**
- Inspiracja: `informacja-dodatkowa/kombinacjach_calculators.py` – kombinatoryczne podejście

**Scenariusze testowe:**
- ✅ remaining_set = 10 dokumentów, próg 150 → 12 dokumentów → generuje warianty które osiągają 100+
- ✅ Deduplikacja: wariant A (pomiń #1) i B (pomiń #2) mają różne dokumenty ale to samo oszczędnęści → keep oba (różne akcje!)
- ✅ Wariant z oszczędnością = 0 → nie generuje
- ✅ Kombinacja: pomiń #1 + zbiorczy Stacja paliw + przesunięcie → 1 wariant
- ✅ Risk_level wariantu = MAX(risk_levels dokumentów) → prawidłowo

**Weryfikacja:**
- Generuje 50-100 wariantów
- Każdy wariant ma oszczędność > 0
- Risk levels są prawidłowe

---

### ✅ Unit 6: Variant Ranker

**Cel:** Rankingowanie TOP 5 wariantów

**Wymagania:** R13

**Zależności:** Unit 5 (Generator), Unit 9 (Memory/History)

**Pliki:**
- Stwórz: `analyzer/ranker.py`
- Test: `tests/test_ranker.py`

**Podejście:**
- Input: ~50-100 wariantów, historia decyzji klienta
- Compatibility score:
  - Jeśli klient poprzednio wybrał warianty z LOW RISK → boost LOW RISK warianty
  - Jeśli klient wybrał warianty z pomijaniami → boost pomijanie warianty
  - Formula: `compatibility = (liczba_matchujących_preferencji / liczba_całych_preferencji)`
- Scoring:
  ```
  score = (
    oszczędność_normalized * 0.5 +
    compatibility_score * 0.3 +
    (1 - risk_level_value) * 0.2
  )
  ```
  (risk_level_value: LOW=0, MED=0.5, HIGH=1)
- Ranking: Sort malejąco po score
- Output: Top 5 wariantów (id, oszczędność, compatibility, risk_level, actions)

**Wzorce do naśladowania:**
- Brak precedensu – nowa logika

**Scenariusze testowe:**
- ✅ Wariant #1 (oszczędzisz 500, LOW, 95% match) > Wariant #2 (oszczędzisz 600, HIGH, 40% match)
- ✅ Historia pusta → compatibility score = baseline (0.5?)
- ✅ TOP 5 zawsze dokładnie 5 wariantów (jeśli 50 wariantów), lub mniej jeśli < 5

**Weryfikacja:**
- TOP 5 są posortowane malejąco po score
- Każdy wariant ma compatibility_score

---

### ✅ Unit 7: Impact Prognozer (Multi-month)

**Cel:** Prognozowanie wpływu przesunięć na następny miesiąc

**Wymagania:** R7

**Zależności:** Unit 5 (Generator), Unit 1 (Parser – dla danych następnego miesiąca)

**Pliki:**
- Stwórz: `analyzer/impact_prognozer.py`
- Test: `tests/test_impact_prognozer.py`

**Podejście:**
- Input: Wariant z przesunięciami, dokumenty następnego miesiąca
- Logic:
  - Dla każdego przesunięcia: ustaw datę = target_month
  - Przelicz: liczba dokumentów w target_month += przesunięte
  - Sprawdź: czy to zmienia próg w target_month?
  - Output: Impact score + message
- Niestety: Nie znamy jeszcze dokumentów następnego miesiąca na MVP
- Fallback: Sugeruj przesunięcie, ale z disclaimer "Grudzień będzie mieć +X dokumentów"

**Wzorce do naśladowania:**
- Brak precedensu

**Scenariusze testowe:**
- ✅ Przesuwasz 3 dokumenty do grudnia, które mają razem 150 dokumentów → progozuje "Grudzień będzie miał 153, możemy tam zoptymalizować"
- ✅ Brak przesunięć → impact_score = 0

**Weryfikacja:**
- Prognozowanie jest matematycznie poprawne

---

### ✅ Unit 8: PDF Output Generator

**Cel:** Generowanie PDF dla księgowej (actionable, z checkboxy)

**Wymagania:** R8, R15

**Zależności:** Unit 5 (Warianty), Unit 8 (Prognozer)

**Pliki:**
- Stwórz: `analyzer/pdf_generator.py`
- Stwórz: `analyzer/templates/pdf_template.py` (layout)
- Test: `tests/test_pdf_generator.py`

**Podejście:**
- Use ReportLab (patrz `raport-kasowy` example)
- Structure:
  1. Header: Klient, forma działalności, miesiąc, data analizy
  2. Summary: "Wybrałeś wariant #3, oszczędzisz 500 zł"
  3. Dla każdej akcji:
     - POMIŃ: lista dokumentów z wartościami, datami
       - Checkbox: "☐ Potwierdzam pomijanie"
     - ZBIORCZY: grupy dostawcy
       - Checkbox: "☐ Potwierdzam zbiorczą"
     - PRZESUNIĘCIE: dokumenty + target month
       - Checkbox: "☐ Potwierdzam przesunięcie"
  4. Risk assessment: Powód każdej oceny
  5. Footer: Instrukcje dla księgowej + legalese

- Użyj DejaVuSans.ttf dla polskich znaków
- Numerowanie stron jeśli jest dużo dokumentów

**Wzorce do naśladowania:**
- `raport-kasowy/pdf_generator.py`
- `informacja-dodatkowa/docx_generator.py` (struktura, nie dokładny kod)

**Scenariusze testowe:**
- ✅ Generuje PDF bez erroru
- ✅ PDF zawiera 5 wariantów (jeśli 5 wybranych)
- ✅ Checkboxy są clickable (form fields w PDF?)
- ✅ Polski tekst się renderuje poprawnie

**Weryfikacja:**
- PDF istnieje i jest otwieralny
- Zawiera wszystkie akcje i checkboxy

---

### ✅ Unit 9: JSON Output + Memory

**Cel:** Serializacja wariantów do JSON + zapis decyzji klienta do dziennika reguł

**Wymagania:** R9, R10

**Zależności:** Unit 5 (Warianty), Unit 3 (Rules)

**Pliki:**
- Stwórz: `analyzer/json_output.py`
- Stwórz: `analyzer/memory.py` (zapis decyzji)
- Test: `tests/test_json_output.py`, `tests/test_memory.py`

**Podejście:**
- JSON Output:
  ```json
  {
    "analiza": {
      "klient_id": "XYZ",
      "miesiąc": "2025-11",
      "data_analizy": "2025-05-26",
      "warianty": [
        {
          "id": 1,
          "oszczędność": 500,
          "dokumenty_do_pomijania": [...],
          "grupy_do_zbiorczenia": [...],
          "dokumenty_do_przesunięcia": [...],
          "risk_level": "LOW",
          "compatibility_score": 0.95
        }
      ]
    }
  }
  ```
- Memory (zapis decyzji):
  - Klient wybiera wariant #3
  - System zapisuje do `rules/klient_XYZ.json`:
    ```json
    {
      "client_decisions": [
        {
          "id": "dec_20250526_nov",
          "miesiąc": "2025-11",
          "wybrany_wariant": 3,
          "oszczędność": 500,
          "data": "2025-05-26",
          "status": "pending_implementation"
        }
      ]
    }
    ```
  - + Tworzy `client_preference` rules dla używanego wariantu

**Wzorce do naśladowania:**
- `polityka-rachunkowosci` – JSON serialization

**Scenariusze testowe:**
- ✅ Wariant se rializuje do poprawnego JSON
- ✅ Decyzja se rializuje do rules JSON
- ✅ Ponowna analiza – widzi poprzednie decyzje

**Weryfikacja:**
- JSON jest valid
- Decyzje są tracowane w rules

---

### ✅ Unit 10: Streamlit UI Orchestration

**Cel:** Interfejs użytkownika – upload JPK_FA, display wariantów, capture decyzji

**Wymagania:** Wszystkie (interface do wszystkiego)

**Zależności:** Wszystkie Units 1-9

**Pliki:**
- Stwórz: `app.py` (main Streamlit app)
- Stwórz: `ui/` folder (components)
  - `ui/header.py` – header + konfiguracja klienta
  - `ui/upload.py` – JPK_FA upload
  - `ui/variants_display.py` – display TOP 5 wariantów
  - `ui/decision_capture.py` – capture decyzji (radio buttons, checkboxy)
  - `ui/pdf_viewer.py` – preview PDF
  
- Test: `tests/test_streamlit_integration.py` (jeśli możliwe)

**Podejście:**
- Flow:
  1. Login / select klient (jeśli multi-klient) → session state
  2. Upload JPK_FA XML
  3. Wyświetl progress: "Parsing... Tax Advisor... Optimizing..."
  4. Display TOP 5 wariantów (tabelka: ID, Oszczędność, Risk, Compatibility)
  5. Klient klika "Select variant #3"
  6. Pokaż szczegóły wariantu #3 (expand view)
  7. Generate PDF + show preview
  8. Klient potwierdza: "Confirm & save"
  9. System zapisuje do JSON, pokazuje confirmation message
- UI Design:
  - Minimalistyczny, czysty layout
  - Abacus branding (navy + gold kolory jeśli są w brand guide)
  - Responsive (mobile-friendly)
  - Dark mode option (based on system preference)
- State management:
  - `session_state['klient_id']`
  - `session_state['uploaded_file']`
  - `session_state['parsed_documents']`
  - `session_state['variants']`
  - `session_state['selected_variant']`

**Wzorce do naśladowania:**
- `informacja-dodatkowa/app.py` – multi-step wizard
- `polityka-rachunkowosci/app.py` – sidebar + main content

**Scenariusze testowe:**
- ✅ Upload JPK_FA → parsing w background
- ✅ Warianty się wyświetlają
- ✅ Click na wariant → expand view
- ✅ Confirm → zapisuje, pokazuje success message
- ✅ PDF preview se renderuje

**Weryfikacja:**
- App startuje bez erroru
- Flow jest intuicyjny
- PDF się generuje na demand

---

### ✅ Unit 11: Config & Deployment Setup

**Cel:** Konfiguracja cennika, forma działalności, deployment do Streamlit Cloud

**Wymagania:** R4 (cennik), deployment

**Zależności:** Wszystkie Units 1-10

**Pliki:**
- Stwórz: `config.json` (ceny, formy działalności)
  ```json
  {
    "ceny": {
      "0-50": 100,
      "51-100": 180,
      "101-200": 280,
      "201-500": 450
    },
    "formy_działalności": ["KPIR", "KSH", "Ryczałt VAT"],
    "system_rules_path": "data/rules_system.json"
  }
  ```
- Stwórz: `.streamlit/config.toml` (Streamlit settings)
- Stwórz: `requirements.txt` (dependencies)
- Stwórz: `.gitignore` (exclude data/rules_klient_*.json, uploads/)
- Stwórz: `README.md` (dokumentacja)

**Podejście:**
- Dependencies:
  - `streamlit>=1.28`
  - `lxml>=4.9`
  - `reportlab>=4.0`
  - `python-dateutil>=2.8`
  - `pydantic>=2.0` (optional, dla validation)
- Streamlit config:
  - Theme: auto (respects system)
  - Page config: wide layout, custom favicon
- `.streamlit/secrets.toml` (dla sensitive data jeśli będzie – na razie nie)
- Deployment: GitHub + Streamlit Cloud

**Wzorce do naśladowania:**
- `informacja-dodatkowa/requirements.txt`
- Standard Streamlit setup

**Scenariusze testowe:**
- ✅ App startuje: `streamlit run app.py`
- ✅ Config sie ładuje
- ✅ Deployment do Streamlit Cloud: `git push` → auto-redeploy

**Weryfikacja:**
- App sie uruchamia lokalnie
- Config sie ładuje bez erroru

---

### ✅ Unit 12: Testing + CI

**Cel:** Unit testy + integration tests + CI workflow

**Wymagania:** Wszystkie (quality gate)

**Zależności:** Wszystkie Units 1-11

**Pliki:**
- Stwórz: `tests/` folder (pytest)
  - `test_parser.py`
  - `test_tax_advisor.py`
  - `test_rules.py`
  - `test_constraints.py`
  - `test_optimizer.py`
  - `test_ranker.py`
  - `test_impact_prognozer.py`
  - `test_pdf_generator.py`
  - `test_json_output.py`
  - `test_memory.py`
  - `test_integration.py` (end-to-end: upload → PDF)
- Stwórz: `.github/workflows/tests.yml` (CI na push/PR)
- Stwórz: `pytest.ini` (pytest config)

**Podejście:**
- Każdy unit ma unit testy (patrz scenariusze w Unit descriptions)
- Integration test: Full flow (JPK_FA → PDF)
- Mocking: Mock external dependencies (jeśli jakieś)
- Coverage: Minimum 70% code coverage (realistyczne dla MVP)
- CI: GitHub Actions
  - Run tests na każdym push
  - Run testy na PR
  - Status check: Musi przejść żeby merge

**Wzorce do naśladowania:**
- Standard pytest + GitHub Actions

**Scenariusze testowe:**
- ✅ Integration: upload test JPK_FA → parser → advisor → optimizer → ranker → PDF
- ✅ Edge cases z każdego unit'a

**Weryfikacja:**
- Testy przechodzą
- Coverage > 70%

---

## Schemat plików (directory structure)

```
analyzer-oszczednosci/
├── app.py                          # main Streamlit app
├── config.json                     # config (ceny, formy działalności)
├── requirements.txt
├── README.md
├── .gitignore
├── .streamlit/
│   └── config.toml
├── .github/
│   └── workflows/
│       └── tests.yml
├── analyzer/
│   ├── __init__.py
│   ├── models.py                   # Document, Variant dataclasses
│   ├── parser.py                   # JPK_FA parser
│   ├── tax_advisor.py              # Risk assessment
│   ├── rules.py                    # Rule engine
│   ├── constraints.py              # Constraint definition
│   ├── optimizer.py                # Variant generator + ranker
│   ├── ranker.py                   # TOP 5 ranking
│   ├── impact_prognozer.py         # Multi-month impact
│   ├── pdf_generator.py            # PDF output
│   ├── json_output.py              # JSON serialization
│   └── memory.py                   # Decision tracking
├── ui/
│   ├── __init__.py
│   ├── header.py                   # UI components
│   ├── upload.py
│   ├── variants_display.py
│   ├── decision_capture.py
│   └── pdf_viewer.py
├── data/
│   ├── rules_system.json           # system rules
│   └── rules_klient_{id}_template.json
├── tests/
│   ├── __init__.py
│   ├── test_parser.py
│   ├── test_tax_advisor.py
│   ├── test_rules.py
│   ├── test_constraints.py
│   ├── test_optimizer.py
│   ├── test_ranker.py
│   ├── test_impact_prognozer.py
│   ├── test_pdf_generator.py
│   ├── test_json_output.py
│   ├── test_memory.py
│   └── test_integration.py
├── fixtures/
│   └── sample_jpk_fa.xml           # test data
└── docs/
    └── IMPLEMENTATION_NOTES.md
```

---

## Wpływ systemowy

### Graf interakcji
```
Streamlit UI (app.py)
├── Parser (unit 1) ← JPK_FA XML
├── Tax Advisor (unit 2) ← parsed documents
├── Rule Engine (unit 3) ← queries
├── Constraints (unit 4) ← tax advisor + rules
├── Optimizer (unit 5) ← constraints
├── Ranker (unit 6) ← variants + memory
├── Impact Prognozer (unit 7) ← variants
├── PDF Generator (unit 8) ← top 5 variants
├── JSON Output (unit 9) ← variants
└── Memory (unit 9) ← decyzja klienta
```

### Propagacja błędów
- Parser error (malformed XML) → log + show error in UI ("Nieprawidłowy plik JPK_FA")
- Tax Advisor error (nie można ocenić dokumentu) → MEDIUM RISK (conservative)
- Rule Engine error (brakujący rules JSON) → use defaults
- Optimizer error (nie mogą być warianty) → show message "Brak możliwości optymalizacji dla tych dokumentów"

### State management
- Streamlit session_state persists across interactions w ramach sesji
- `data/rules_klient_{id}.json` persist across sessions

---

## Ryzyka i zależności

### Ryzyka

1. **Risk: JPK_FA format zmienność** (Medium)
   - JPK_FA ma różne wersje, namespace'i mogą się zmienić
   - **Mitygacja:** Testy na wielu przykładach JPK_FA, flexible namespace handling

2. **Risk: Performance na dużych zbiorach** (Low-Medium)
   - Jeśli klient ma 1000+ dokumentów, optimizer może być wolny
   - **Mitygacja:** Caching, possible numpy/pandas optimization w Phase 2

3. **Risk: Tax rules nie pokrywają wszystkie case'i** (Medium)
   - KPIR/KSH/Ryczałt to uproszczenie, mogą być edge case'i
   - **Mitygacja:** Flag dla tax advisor "uncertain" + log, user manual override

4. **Risk: PDF renderowanie z polskimi znakami** (Low)
   - ReportLab może mieć problemy z literami
   - **Mitygacja:** DejaVuSans.ttf (sprawdzane w raport-kasowy), testy

### Zależności

1. **Zależność technologiczna:** Streamlit Cloud dostęp (dla deployment'u)
2. **Zależność biznesowa:** Klient musi dostarczyć JPK_FA (ręcznie na MVP)
3. **Zależność kontekstowa:** Reguły podatkowwe mogą zmienić się (2027+) – trzeba będzie update

---

## Harmonogram i sekwencjonowanie

### Faza 1: Core parsowanie + risk assessment (Unit 1-4)
- Implementuj Parser (Unit 1) → możesz testować na real JPK_FA
- Implementuj Tax Advisor (Unit 2) → rules-based ocena
- Implementuj Rule Engine (Unit 3) → persist reguł
- Implementuj Constraints (Unit 4) → zidentyfikuj no-go docs
- **Timeframe:** ~3-4 dni

### Faza 2: Optimization (Unit 5-6)
- Implementuj Optimizer (Unit 5) → generuj warianty
- Implementuj Ranker (Unit 6) → TOP 5
- Implementuj Impact Prognozer (Unit 7) → multi-month
- **Timeframe:** ~2-3 dni

### Faza 3: Output + Memory (Unit 8-9)
- Implementuj PDF Generator (Unit 8)
- Implementuj JSON Output + Memory (Unit 9)
- **Timeframe:** ~2 dni

### Faza 4: UI + Integration (Unit 10-12)
- Implementuj Streamlit UI (Unit 10)
- Implementuj Config/Deployment (Unit 11)
- Implementuj Testing (Unit 12)
- **Timeframe:** ~3-4 dni

**Total estimated:** 10-14 dni (z testingiem + review)

---

## Dokumentacja / Notatki operacyjne

### MVP Launch
- Instrukcja deployment do Streamlit Cloud
- User guide: Jak uploadować JPK_FA, czytać warianty, confirm decyzje
- Tax rules documentation (jakie formy działalności obsługiwane, jakie reguły)

### Phase 2 (Future)
- Integracja z Frappe CRM
- Supabase persistence (zamiast JSON)
- Enova 365 Web API integration (zamiast ręczny upload)
- Notification system (alert gdy blisko progu)
- Pełne formy działalności (FPP, spółdzielnie, itp.)

---

## Źródła i referencje

**Dokument źródłowy:**
- `/home/claude/analyzer-oszczednosci-comprehensive-requirements.md`

**Powiązane istniejące kody:**
- `ift2r-generator/` – JPK_FA parsing pattern
- `raport-kasowy/` – PDF generation pattern
- `informacja-dodatkowa/` – Streamlit UI pattern
- `polityka-rachunkowosci/` – Multi-step wizard

**Zewnętrzne dokumenty:**
- JPK_FA XSD: [oficjalny MF dokument, jeśli dostępny]
- Streamlit docs: https://docs.streamlit.io
- ReportLab docs: https://www.reportlab.com/docs/reportlab-userguide.pdf

---

## Kluczowe decyzje (podsumowanie)

| Decyzja | Uzasadnienie |
|---------|-------------|
| D1: Modułowa architektura | Testowalna, maintainable |
| D2: Dataclass Document | Type-safe, serializable |
| D3: JSON Rule Engine | Edytowalny, queryable |
| D4: Atomic Variant | Proste do komunikacji |
| D5: ReportLab PDF | Deterministyczne, polskie znaki |
| D6: Weighted scoring | Finansowe + personalne + bezpieczeństwo |
| Architektura MVP | Streamlit + JSON (bez Frappe/Supabase na start) |

---

## Status

✅ **Gotowy do implementacji**

Wszystkie decyzje produktowe są rozstrzygnięte. Implementation units są konkretne i gotowe do kodowania.

Rekomendowany start: Unit 1 (Parser) → Unit 2 (Tax Advisor) → rest w sekwencji.

