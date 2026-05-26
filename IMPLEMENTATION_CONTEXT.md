# Analyzer Oszczędności – Implementation Context

## Szybki start

**Plan:** `/home/claude/docs/plans/2026-05-26-analyzer-oszczednosci-implementation-plan.md`
**Requirements:** `/home/claude/analyzer-oszczednosci-comprehensive-requirements.md`

## Faza 1: Core parsowanie + risk assessment

### Unit 1: JPK_FA Parser (START TUTAJ)

**Cel:** Ekstrahuj dokumenty z JPK_FA XML

**Pliki do stworzenia:**
```
analyzer/models.py          # Document dataclass
analyzer/parser.py          # JPK_FA parser
tests/test_parser.py        # testy
```

**Document dataclass structure:**
```python
@dataclass
class Document:
    id: str                      # unique ID z JPK_FA
    numer: str
    data: datetime
    nip_dostawcy: str
    wartość: Decimal
    typ: str                     # KP, NT, KD
    typ_płatności: str           # gotówka / przelew
    risk_level: str = None       # LOW/MED/HIGH
    status: str = "new"
    historia: List[Dict] = field(default_factory=list)
```

**Parser expectations:**
- Use `lxml.etree` (pattern z ift2r-generator)
- Ekstrahuj: numer, data, NIP dostawcy, wartość, typ, typ_płatności
- Handle currencies properly
- Error handling: log nievalid documenty, nie failuj całej analizy

**Test scenarios:**
- ✅ Prawidłowy JPK_FA → ekstrahuje dokumenty
- ✅ Negna wartość (korekta) → ekstrahuje prawidłowo
- ✅ Malformed XML → handles gracefully
- ✅ Pusta lista dokumentów → []

---

### Unit 2: Tax Advisor Agent

**Cel:** Ocena RISK_LEVEL (LOW/MED/HIGH)

**Pliki:**
```
analyzer/tax_advisor.py
data/rules_system.json      # system rules
tests/test_tax_advisor.py
```

**Logic:**
1. KPIR + gotówka + <50 zł → LOW
2. KPIR + przelew + duża wartość → MEDIUM
3. KSH + przelew → HIGH (zawsze!)
4. NT (nota) → LOW
5. Query dziennika reguł dla custom rules

---

### Unit 3: Rule Engine

**Cel:** Zarządzanie dziennika reguł

**Pliki:**
```
analyzer/rules.py
data/rules_system.json
data/rules_klient_{id}_template.json
tests/test_rules.py
```

**Functions:**
- `load_rules(klient_id)` → merge system + client rules
- `query_rule(dokument)` → jaka reguła pasuje?
- `add_rule(klient_id, rule)` → zapisz nową rule
- Tracking: `liczba_zastosowań`

---

### Unit 4: Constraints

**Cel:** Zidentyfikuj dokumenty NO-GO

**Output:**
- `no_go_documents` → HIGH RISK + nie_można_ruszać rules
- `remaining_set` → dokumenty do optymalizacji

---

## Wzorce do naśladowania

### JPK_FA Parsing
- `ift2r-generator/main.py` – namespace handling
- `raport-kasowy/parsers/jpk_fa_parser.py` – typ_płatności extraction

### Streamlit patterns
- `informacja-dodatkowa/app.py` – session_state, multi-step
- `polityka-rachunkowosci/app.py` – sidebar config

### PDF generation
- `raport-kasowy/pdf_generator.py` – ReportLab pattern
- DejaVuSans.ttf dla polskich znaków

---

## Dependencies (dla requirements.txt)

```
streamlit>=1.28
lxml>=4.9
reportlab>=4.0
python-dateutil>=2.8
pytest>=7.0
```

---

## Git workflow (w Claude Code)

```bash
# Start
git init
git add .
git commit -m "init: project structure"

# Po każdym Unit
git add analyzer/xxx.py tests/test_xxx.py
git commit -m "feat: Unit X - [opis]"

# Push na GitHub
git push origin main
```

---

## Quick reference: Requirements traceability

| Unit | Wymagania |
|------|-----------|
| 1. Parser | R1 |
| 2. Tax Advisor | R3 |
| 3. Rules | R4, R9 |
| 4. Constraints | R5 |
| 5. Optimizer | R6 |
| 6. Ranker | R13 |
| 7. Impact | R7 |
| 8. PDF | R8, R15 |
| 9. JSON+Memory | R10 |
| 10. UI | R14, all |
| 11. Config | R4, deploy |
| 12. Testing | quality |

---

## Notes

- **Prioritas:** Unit 1-4 są blockers dla reszty
- **Testing:** Testy na bieżąco, nie na koniec
- **Mockowanie:** Jeśli trzeba external dependencies, mockuj
- **Logging:** Comprehensive logging dla tax advisor decisions

---

Gotów do implementacji! Zaraz Claude Code przejmie.
