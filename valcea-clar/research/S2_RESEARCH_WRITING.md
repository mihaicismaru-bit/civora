# VÂLCEA CLAR — S2 Research & Writing

**Data:** 22 septembrie 2026  
**Statut:** implementare operațională S2

S2 mută centrul de greutate de la volum de crawling la muncă editorială: un nucleu mic de surse prioritare, o agendă explicită și formate care arată ce adaugă redacția peste simpla reproducere a unei surse.

## Livrabile

- `s2_priority_sources.json` — nucleul de 27 de surse. Este în intervalul pilot 20–30 și combină feeduri oficiale, surse primare de verificare, registre documentare și două publicații locale folosite numai pentru descoperire.
- `s2_editorial_agenda_2026-09-22.json` — agenda curentă cu unghi, dovadă, gol de verificare și următorul punct de urmărit.
- `../editorial/s2_format_examples.json` — trei produse editoriale complete pentru acceptanța S2: știre, explicativ și utilitar.
- `../scripts/validate_s2_research_writing.py` — verifică mecanic condițiile de acceptanță.

## Reguli

1. T1/T1B au prioritate pentru fapte materiale; T2 poate porni semnalul și poate susține contextul, dar nu primește automat autoritate primară.
2. Fiecare subiect trebuie să noteze explicit ce știm, ce nu știm și ce urmează.
3. Un explicativ poate face calcule editoriale doar dacă formulele sunt reproductibile din cifrele sursă și sunt etichetate ca derivate.
4. Un material utilitar trebuie să limiteze aria, intervalul și efectul la ceea ce documentul chiar spune.
5. Niciun fișier S2 nu are autoritate de publicare. Publicarea trece prin traseul editorial și S1.

## Criteriul de închidere S2

S2 este acceptat când:
- registrul are între 20 și 30 de surse, acoperă verticalele majore și conține ancore pentru Brezoi–Lotru–Valea Oltului;
- există o agendă cu dovezi și goluri de verificare;
- există exact cele trei forme minime (`straight_news`, `explainer`, `service_news`), fiecare cu surse, aport editorial și limitări;
- validatorul și quality gate trec fără a da acestor fișiere autoritate de publicare.
