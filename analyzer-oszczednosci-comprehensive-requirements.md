---
date: 2026-05-26
topic: analyzer-oszczednosci-comprehensive
---

# Analyzer Oszczędności Dokumentów v2.0
## Z Tax Advisor Agent i Rule Engine

---

## Problem

Klienci Abacus Centrum Księgowe (200 firm) płacą za księgowanie dokumentów na podstawie **ilościowych progów** (0-50 dok, 51-100 dok, 101-200 dok, itd.). 

**Główne bóle:**
- Klient płaci za próg 101-200 dokumentów, a ma 152 (tracą na tym)
- Klient ma 10 małych faktur za 15 zł każda, ale to liczy się jako 10 dokumentów
- Klient nie wie, że mógłby negocjować zbiorczą z dostawcą lub przesunąć faktury do następnego miesiąca
- Księgowy ręcznie sprawdza co można zrobić – czasochłonne

**Co się zmienia:**
System automatycznie analizuje dokumenty i **sugeruje konkretne scenariusze optymalizacji** (pomijanie, zbiorcze, przesunięcia), z uwzględnieniem:
- Formy działalności (KPIR, KSH, Ryczałt VAT)
- Reguł podatkowych (co można bezpiecznie zrobić)
- Historii preferencji klienta (się uczy czego klient lubi)

---

## Wymagania

### R1. Parsing JPK_FA
- System parsuje ręcznie uplodowany plik JPK_FA XML
- Ekstrahuje: numer faktury, datę, NIP dostawcy, wartość, typ (KP/NT/KD), typ płatności (gotówka/przelew)
- Waliduje strukturę vs MF whitelist API (docelowo, MVP może bez tego)

### R2. Definicja dokumentu (dwie warstwy)
- **Warstwa 1 (dokumenty):** Atomarne jednostki z JPK_FA (każda faktura)
- **Warstwa 2 (grupy):** Dokumenty zgrupowane: `{data + dostawca + typ}`
  - Grupy służą do sugerowania faktur zbiorczych
  - Dokumenty służą do sugerowania pomijania/przesunięcia

### R3. Tax Advisor Agent
- **Niezależny moduł** analizujący każdy dokument vs reguły z dziennika
- Każdy dokument dostaje ocenę: `RISK_LEVEL` (HIGH/MEDIUM/LOW)
- Ocena bazuje na:
  - Formie działalności klienta (PKD → zasady podatku)
  - Typ dokumentu (KP, NT, KD)
  - Typ płatności (gotówka vs przelew)
  - Wartość dokumentu
  - Tagi z dziennika reguł
- **Output:** Każdy dokument ma score ryzyka + powód oceny

### R4. Rule Engine (Dziennik Reguł)
- **Hybrid storage:** JSON file (`rules/klient_{ID}.json`) + docelowo Frappe DocType
- **Dwa typy reguł:**
  1. **System rules** (dodane przez Abacus/tax advisor)
  2. **Client rules** (wyuczone z historii decyzji klienta)
- **Struktura reguły:**
  ```json
  {
    "id": "unique_id",
    "nazwa": "Human-readable name",
    "klient": "XYZ", // lub ["ABC", "XYZ"] dla wielu
    "typ": "system" | "client_preference",
    "źródło": "manual" | "decision_2025_05_26_november",
    "reguła": "forma='KPIR' AND wartość < 50",
    "działanie": "sugeruj_pomijanie" | "sugeruj_zbiorczy" | "sugeruj_przesunięcie",
    "priorytet": 1-10,
    "tagi": ["KPIR", "małe_dokumenty"],
    "data_utworzenia": "2025-05-26",
    "liczba_zastosowań": 3,
    "data_ostatniego_użycia": "2025-05-26"
  }
  ```
- **Formy działalności obsługiwane:**
  - KPIR + Ryczałt VAT: priorytet = duże faktury (rozsądne uzasadnienie)
  - Księgi handlowe: gotówkowe można ruszać, przelew = nie do zmiany
  - (rozszerzalne)

### R5. Algorytm analizy – Constraint-based
1. **Parser:** JPK_FA → dokumenty
2. **Tax Advisor:** każdy dokument → RISK_LEVEL
3. **Constraint definition:** Advisor identyfikuje dokumenty NO-GO (nie można ruszać)
4. **Search space:** Analyzer generuje warianty na remaining set
5. **Warianty:** Kombinacje trzech strategii:
   - **Pomijanie:** które dokumenty pominąć (nie księgować)
   - **Zbiorcze:** które grupy dostawcy scalić w zbiorczą (sugestia do klienta)
   - **Przesunięcia:** które dokumenty przesunąć do następnego miesiąca
6. **Ranking:** TOP 5 wariantów rankingowane po:
   - Oszczędności (głównie)
   - Match score z historią klienta (+compatibility)
   - Risk level (LOW first)

### R6. Generowanie wariantów
- **Przestrzeń poszukiwań:** Ambitna (B) – kombinacje kombinacji
  - Pojedyncze akcje + kombinacje akcji
  - Generowanie ~50-100 wariantów, deduplikacja, TOP 5
- **Dla każdego wariantu liczy:**
  - Nowa liczba dokumentów po akcjach
  - Nowy próg (który pakiet będzie?)
  - Oszczędność (różnica między starą ceną a nową)
  - Risk level (MAX z ryzyk wszystkich dokumentów w wariancie)

### R7. Impact prognozowania – Przesunięcia wpływają na następny miesiąc
- Jeśli wariant sugeruje przesunięcie faktur do grudnia:
  - System oblicza: "Grudzień będzie mieć X dokumentów + te przesunięte = Y"
  - Pokazuje: "Grudzień będzie blisko progu, ale tam możemy zoptymalizować inaczej"
  - Klient widzi full picture dla 2 miesięcy

### R8. Output: TOP 5 wariantów
- **Format:** PDF + JSON (dla future Frappe)
- **Dla każdego wariantu:**
  - Numer wariantu + oszczędność (głównie)
  - Szczegóły akcji:
    - Dokumenty do pomijania (z wartościami, datami, powodami)
    - Dokumenty do zbiorczenia (które grupy, powód)
    - Dokumenty do przesunięcia (które, do którego miesiąca, impact)
  - Risk assessment (ryzyk dla każdego dokumentu + ogólnie)
  - Audit trail (dlaczego Tax Advisor się tym zajął, jakie reguły zagrały)
- **Actionable dla księgowej:** Checkboxy "Potwierdzam pomijanie", "Potwierdzam zbiorczą", itp.

### R9. Decyzje klienta – Pamiętanie i uczenie się
- **Gdzie:** Dziennik reguł (typ: `client_preference`)
- **Co pamiętamy:**
  - Którą warianty klient wybrał
  - Które dokumenty akceptował do pomijania
  - Które grupy do zbiorczenia
  - Które przesunięcia wykonał
  - Datę decyzji, miesiąc, oszczędność
- **Jak uczymy się:**
  - Po 3+ decyzjach tego samego typu → tworzymy `client_preference` rule
  - Np. "Klient zawsze wybiera LOW RISK" → boost LOW RISK wariantów dla niego
  - Compatibility score wariantów rosnący dla "jego stylu"

### R10. Persistence – MVP do Frappe
- **MVP:**
  - `rules/klient_{ID}.json` - dziennik reguł (system + client rules)
  - `decisions/klient_{ID}.json` - historia decyzji
  - PDF/JSON output z każdej analizy
- **Docelowo:**
  - Frappe DocType: `TaxRule`
  - Frappe DocType: `OptimizationDecision`
  - Dashboard klienta w Frappe CRM

### R11. Okres analizy
- **Horyzont:** Roczny (styczeń-grudzień, potem reset)
- **Raport roczny:** Trend analysis (które miesiące problematyczne, gdzie optymalizować)
- **Prognozowanie:** "Jeśli będziesz optymalizować tak jak sugerujemy, zaoszczędzisz ~3000 zł w roku"

### R12. Alert system – Real-time
- Kiedy klient jest blisko progu (np. 145 dokumentów, próg 150):
  - "Jesteś blisko progu. Jeśli teraz przesuniesz 3 faktury, zaoszczędzisz 200 zł"
  - Alert w Streamlit (MVP), docelowo push notification w Frappe

### R13. Ranking i personalizacja
- **TOP 5 wariantów rankingowane po:**
  1. Oszczędności (głównie)
  2. Match score z historią klienta (compatibility)
  3. Risk level (LOW > MEDIUM > HIGH)
- **Compatibility score:** Bazuje na dzienniku reguł typu `client_preference`
  - Np. Wariant #1 ma 95% match (wszystkie dokumenty typu które klient wcześniej akceptował)
  - Wariant #5 ma 58% match (mix ryzyk, inne style)

### R14. Brak "nakazania" – Tylko rekomendacje
- **KRITYCZNE:** System NIGDY nie robi czegoś automatycznie
- System tylko SUGERUJE, klient DECYDUJE
- Przykład:
  - ❌ "Pomiń tę fakturę" → ✅ "Sugerujemy pominąć tę fakturę"
  - ❌ "Zrób zbiorczą" → ✅ "Zaproponuj dostawcy zbiorczą"
  - ❌ "Przesuniesz do grudnia" → ✅ "Możesz przesunąć do grudnia"
- Decyzja zawsze u klienta

### R15. Handoff do księgowej – Dokumentacja decyzji
- **Format:** PDF + JSON
- **PDF zawiera:**
  - Jasne instrukcje: "DO POMIJANIA", "DO ZBIORCZENIA", "DO PRZESUNIĘCIA"
  - Checkboxy: "Potwierdzam pomijanie"
  - Dla każdej akcji: konkretne dokumenty, wartości, daty
  - Audit trail: dlaczego te dokumenty
- **JSON zawiera:** Strukturalne dane dla future API/Frappe

---

## Kryteria sukcesu

- **K1:** System prawidłowo parsuje JPK_FA i ekstrahuje dokumenty
- **K2:** Tax Advisor poprawnie ocenia RISK_LEVEL dla każdego dokumentu (testowane na known rules)
- **K3:** Generuje TOP 5 wariantów z co najmniej 50% kombinacji (nie każdego możliwego wariantu, ale solidna coverage)
- **K4:** Oszczędności są matematycznie poprawne (unterschied ceny przed/po)
- **K5:** Decyzje klienta są pamiętane i wpływają na kolejne analizy
- **K6:** PDF jest actionable – księgowy wie dokładnie co robić
- **K7:** System uczy się preferencji klienta (compatibility score rośnie z czaseńcie)
- **K8:** TOP 5 wariantów są różnorodne (mix strategii, nie duplikaty)

---

## Granice scope'u (Non-goals)

- **Non-G1:** System nie zmienia faktур automatycznie ani nie wysyła do Enovy (to zawsze rób klient/księgowy)
- **Non-G2:** Nie obsługujemy wszystkich form działalności (tylko KPIR, KSH, Ryczałt VAT na start)
- **Non-G3:** Nie integrujemy z Enova API na MVP (JSON upload JPK_FA)
- **Non-G4:** Nie budujemy UI do zarządzania rules (JSON edytowalny ręcznie, opcjonalnie Streamlit sidebar)
- **Non-G5:** Nie robimy full Frappe integration (to Phase 2) – MVP to Streamlit

---

## Kluczowe decyzje

### D1: Constraint-based algorytm
**Decyzja:** Tax Advisor first definiuje NO-GO dokumenty, Analyzer pracuje na remaining set.
**Uzasadnienie:** Bezpieczeństwo – nie chcemy sugerować manipulacji dokumentami które są obowiązkowe/risky.

### D2: Dwie warstwy dokumentów (atomarne + grupy)
**Decyzja:** Dokumenty dla pomijania/przesunięcia, grupy dla zbiorczych.
**Uzasadnienie:** Zbiorczy wymaga zgody dostawcy (grupy mają sens), pomijanie to indywidualna decyzja (dokumenty).

### D3: Dziennik reguł = system + client memory
**Decyzja:** Jedna struktura JSON przechowuje zarówno reguły systemowe jak i wyuczone preferencje klienta.
**Uzasadnienie:** Singlena source of truth, łatwe uczenie się, proste persistence.

### D4: TOP 5 wariantów z compatibility scoring
**Decyzja:** Nie TOP 10, tylko TOP 5. Rankingowanie po: oszczędności, compatibility, risk.
**Uzasadnienie:** 5 to wystarczająco opcji bez choice paralysis. Compatibility robi system bardziej personal.

### D5: PDF + JSON output
**Decyzja:** PDF dla księgowej (actionable), JSON dla future Frappe/API.
**Uzasadnienie:** PDF jest czytelny dla ludzi, JSON jest strukturalny dla maszyn.

### D6: Klient zawsze decyduje
**Decyzja:** System NIGDY nie robi czegoś automatycznie. Zawsze sugestia → decyzja klienta.
**Uzasadnienie:** Odpowiedzialność, bezpieczeństwo podatkowe, compliance.

---

## Zależności / Założenia

- **Z1:** Klient dostarcza JPK_FA XML (ręcznie) – jest w poprawnym formacie
- **Z2:** Widełki cennikowe są znane (0-50, 51-100, itp.) – przechowywane w `config.json`
- **Z3:** Reguły podatkowe dla KPIR/KSH/Ryczałtu są wstępnie skonfigurowane w `rules/system.json`
- **Z4:** Księgowy ma dostęp do PDF i może potwierdzić decyzje (signnature, checkboxy)
- **Z5:** Frappe CRM będzie dostępny dla Phase 2 (docelowo)

---

## Otwarte pytania

### Do rozwiązania przed planowaniem

Brak – wszystkie decyzje produktowe zostały rozstrzygnięte.

### Odroczone do planowania

- **[Wymaga researchu]** Jak dokładnie parsować JPK_FA XML – jaka struktura, namespaces? (Sprawdzić istniejące parsery w repo, np. z ift2r-generator)
- **[Wymaga researchu]** Czy istnieją gotowe biblioteki do validation JPK_FA vs MF whitelist?
- **[Techniczne]** Jaka struktura bazy dla `rules/klient_{ID}.json` – nested vs flat? (Zależy od YAGNI)
- **[Techniczne]** Jak persistować dziennik reguł – JSON file vs Supabase na MVP? (Rekomendacja: JSON file w /data, later Supabase)
- **[Techniczne]** Jaki algorytm rankowania wariantów – weighted scoring czy coś prostszego? (Rekomendacja: weighted scoring: oszczędność 50%, compatibility 30%, risk 20%)

---

## Następne kroki

→ **`/dev-plan`** do planowania technicznego implementacji

---

## Architektura high-level (dla kontekstu)

```
INPUT: JPK_FA XML (client upload)
  ↓
PARSER: ExtrahujDocumenty {id, nip, data, wartość, typ, typ_płatności}
  ↓
TAX_ADVISOR_AGENT: Każdy dokument → RISK_LEVEL (HIGH/MED/LOW)
  ↓
RULE_ENGINE: Ładuj rules/klient_{ID}.json (system + client_preference rules)
  ↓
ANALYZER_SEARCH: Generuj ~50-100 wariantów (kombinacje pomijania+zbiorczych+przesunięć)
  ↓
RANKING: TOP 5 wariantów (oszczędność, compatibility, risk)
  ↓
OUTPUT: PDF (dla księgowej) + JSON (dla persistence/Frappe)
  ↓
MEMORY: Zapisz decyzję klienta → dziennik reguł (typ: client_preference)
  ↓
LOOP: Następny miesiąc → system już wie preferencje klienta
```

---

## Statusy dokumentów (dla implementacji)

Każdy dokument w systemie może mieć status:
- `NEW` – parsowany z JPK_FA, nie oceniany
- `RISK_ASSESSED` – Tax Advisor już ocenił
- `IN_VARIANT_X` – dokument jest w wariancie #X do wybrania
- `SELECTED` – klient wybrał ten wariant
- `CONFIRMED_BY_ACCOUNTANT` – księgowy potwierdził akcję
- `EXECUTED` – akcja wykonana (przesunięcie, pominięcie, zbiorczy wysłany)
- `ARCHIVED` – koniec roku, zaarchiwizowano

---

## Metryki do trackowania (dla Phase 2)

- Liczba analizowanych dokumentów/miesiąc
- Średnia oszczędność na klienta/rok
- Adoption rate wariantów (ile klientów akceptuje które warianty)
- ROI na Abacusa (koszt development vs oszczędność dla klientów)
- Tax advisor accuracy (ile razy reguły się okazały poprawne)

---

## Przykład flow – Fryzjer XYZ, KPIR, Listopad 2025

1. **Upload:** Klient uploaduje JPK_FA dla listopada
2. **Parse:** System ekstrahuje 145 dokumentów
3. **Tax Advisor:** Ocenia każdy
   - Faktury od Stacji paliw: LOW RISK (usługa, KPIR ok, gotówka)
   - Druki za 15 zł: LOW RISK (materiały biurowe, mała wartość)
   - Fotel stomatologiczny: HIGH RISK (spoza PKD fryzjera)
4. **Rules:** Ładuje `rules/klient_XYZ.json`
   - System rule: "KPIR, wartość < 50 → sugeruj pomijanie"
   - Client rule (z października): "zawsze wybierasz LOW RISK"
5. **Search:** Generuje warianty
   - Wariant #1: Pomiń 3 faktury (15+20+45 zł), zbiorczy Stacja paliw (5→1) = 99 dokumentów
   - Wariant #2: Tylko zbiorczy Stacja paliw = 141 dokumentów
   - Wariant #3: Pomiń 3 + przesuniesz fakturę do grudnia = 99 dokum., december +1
   - Wariant #4: Przesuniesz 5 faktur do grudnia = 140 dokumentów
   - Wariant #5: Pomiń wszystko poniżej 50 zł (10 faktur) = 135 dokumentów
6. **Ranking:** TOP 5 (już listed powyżej)
   - Wariant #1: 95% match (LOW RISK, pomijania) → oszczędzisz 500 zł
   - Wariant #3: 87% match (LOW RISK + przesunięcia) → oszczędzisz 480 zł
   - Wariant #2: 70% match (tylko zbiorczy, mniej agresywny) → oszczędzisz 200 zł
   - ...
7. **Output:** PDF dla klienta + JSON
8. **Decyzja:** Klient wybiera wariant #1
9. **PDF dla księgowej:** "POMIŃ: faktury #X, #Y, #Z. ZBIORCZY: Stacja paliw..."
10. **Memory:** Zapisz do `rules/klient_XYZ.json` (client_preference: "gra niskim ryzykiem")

---

## Terminologia

- **Dokument** – pojedyncza faktura z JPK_FA
- **Grupa** – dokumenty o tym samym (data + dostawca + typ)
- **Wariant** – konkretna kombinacja akcji (pomijania + zbiorczych + przesunięć)
- **Risk Level** – ocena Tax Advisora (HIGH/MEDIUM/LOW)
- **Oszczędność** – różnica w cenie między obecnym progiem a nowym
- **Compatibility** – jak dobrze wariant pasuje do historii klienta
- **Dziennik reguł** – JSON z system rules + client preferences
- **Handoff** – przekazanie decyzji klienta do księgowej (PDF + JSON)

