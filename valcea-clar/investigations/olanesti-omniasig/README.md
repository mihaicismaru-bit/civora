# Monitorizare — podul pietonal-ciclist peste Olănești, lângă Omniasig

## Încadrare editorială

- **Secțiune principală:** Investigații
- **Desk:** Bani publici și infrastructură
- **Secțiuni secundare:** Oraș; Fonduri europene
- **Stare publică:** `PREPUBLICATION_MONITORING`
- **Dosar editorial:** GitHub issue #59

Subiectul nu este tratat ca o simplă știre de șantier. Monitorizarea urmărește simultan achiziția publică, repartizarea lucrărilor în asociere și subcontractare, lucrările în albia râului, avizele, calendarul, plățile și controlul calității.

## Automatizare

`monitor.py` rulează de două ori pe zi prin GitHub Actions și:

1. verifică sursele oficiale și radarele de presă;
2. extrage numai fragmentele relevante pentru dosar;
3. calculează hash-uri semantice stabile;
4. păstrează ultimul rezultat bun dacă o sursă cade;
5. comentează automat în issue #59 numai la schimbări materiale, după trei eșecuri consecutive sau la revenirea unei surse;
6. nu publică articole și nu formulează acuzații.

Sursele T3 sunt folosite doar pentru descoperire. Orice informație din acestea trebuie confirmată printr-un document sau o sursă calificată înainte de publicare.

## Monitorizare de teren

Automatizarea online nu înlocuiește terenul. Setul minim recomandat, săptămânal sau după o schimbare materială:

- fotografie din același punct de lângă Omniasig;
- fotografie a panoului de identificare a construcției;
- siglele de pe utilaje, containere și veste;
- starea albiei și soluția temporară de dirijare a apei;
- împrejmuirea și accesul public;
- elementele noi de structură care devin ulterior inaccesibile.

## Prag de publicare

Un material factual poate fi pregătit după confirmarea amplasamentului și a contractului. O anchetă acuzatorie rămâne blocată până la obținerea raportului procedurii, acordului de asociere, repartizării subcontractării, actelor de gospodărire a apelor și documentelor de plată/control.
