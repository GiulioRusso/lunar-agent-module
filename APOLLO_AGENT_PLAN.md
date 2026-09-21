# LUMINARY-AGENT — Piano di esecuzione v5 (simulatore prima, agente dopo)

## 0. Decisione di prodotto

Il progetto viene realizzato in questo ordine non negoziabile:

1. completare e verificare il **simulatore desktop**;
2. produrre un `README-simulator.md` didattico che spiega il codice senza presupporre conoscenze;
3. inserire l'agente locale come una policy sostituibile del simulatore già finito;
4. solo allora ampliare gli scenari e fare benchmark/ablazioni.

Il primo deliverable non è quindi un LLM che commenta una discesa, ma un simulatore che si può
lanciare e osservare con un comando: Luminary 099 esegue nel vero emulatore yaAGC, il LEM è
modellato da una pianta locale, e una finestra nativa mostra chiaramente che cosa sta avvenendo.

Target: MacBook Air M5, 16 GB. Tutto gira localmente: niente API cloud, chiavi, servizi a pagamento
o browser. Un eventuale backend Ollama è ammesso soltanto come processo locale via loopback e con
modello già installato; se “nessuna API” include anche loopback, si usa un backend in-process
`llama.cpp` mantenendo la medesima interfaccia Policy.

---

## 1. Definizione tecnica onesta

### 1.1 “Vero AGC”

- Il rope **Luminary 099 originale** viene assemblato ed eseguito da `yaAGC`.
- I/O, DSKY e uplink passano dai meccanismi AGC: socket channel e programma P27; non si pilota il
  LEM scrivendo direttamente la memoria dell'AGC.
- VirtualAGC non include una fisica del LEM: pianta, sensori, radar, terreno e visualizzazione sono
  codice del progetto.
- Il modo stepped veloce usa una patch host-side riproducibile di yaAGC (`--free-run`) che modifica
  il pacing dell'emulatore, **non** Luminary. Non dire “emulatore non modificato”; dire invece:
  **“Luminary originale su yaAGC con patch di pacing host-side, documentata e hashata.”**

Per ogni episodio bisogna salvare: commit VirtualAGC, SHA-256 delle patch applicate, SHA-256 di
yaAGC, rope `.bin` e listing, commit del progetto e stato dirty. La soluzione preferita è costruire
la versione patchata in un worktree/cache di build, lasciando il submodule pinning immutato.

### 1.2 Modello LEM fedele, originale e non generico

Il LEM visualizzato deve essere una mesh **progettata nel repository**, non un asset 3D scaricato o
una navicella generica mascherata da LEM. Deve essere visivamente e dimensionalmente riconoscibile
come Apollo Lunar Module:

- due stadi distinti (descent e ascent stage), struttura ottagonale/asimmetrica, quattro landing
  gear, disco/ugello del DPS, RCS/quadranti e antenna nella silhouette;
- proporzioni e posizioni derivate da fonti tecniche pubbliche, annotate in
  `docs/lem-model-sources.md` con figura/pagina e licenza;
- mesh low-poly/procedurale originale (`lem_mesh.py` oppure asset generato dal repo), con parametri
  numerici, senza importare o ricalcare una mesh esistente;
- per l'MVP è richiesto un modello wireframe/flat shaded accurato nella silhouette, non una resa
  fotorealistica. Texture, decal e materiali storici sono fuori scope;
- stadio e parti devono rispecchiare la configurazione simulata. Se la pianta non ha ancora
  6-DoF, la rotazione visiva rappresenta il pitch/comando disponibile e non deve essere presentata
  come assetto dinamico completo.

Il requisito “uguale all'originale” significa fedeltà a geometria e proporzioni documentate, non
la copia di un asset protetto o di una mesh altrui.

### 1.3 Azioni disponibili oggi

La seam già presente permette a una policy di:

1. mantenere l'automatico (`hold`);
2. prendere il controllo manuale (`take_manual`);
3. impostare rateo verticale e velocità orizzontale desiderati al controllore deterministico
   (`set_manual_target`).

Non sono ancora implementabili in modo onesto: abort con ascent stage, LPD/redesignation,
P64→P66 via MARKRUPT, accettazione radar dentro Luminary e gestione di 1201/1202 realmente
indotti. L'MVP dell'agente va descritto come **equipaggio virtuale che decide il takeover e guida
l'atterraggio in presenza di incertezza osservabile**, non come copertura completa delle procedure
Apollo.

### 1.4 Giudizi di atterraggio

Tenere separati:

| Esito | Criterio |
|---|---|
| `soft_touchdown` | contatto, velocità verticale ≤ 3.0 m/s, orizzontale ≤ 1.2 m/s, propellente > 0 |
| `mission_success` | `soft_touchdown` + errore target ≤ 100 m + area senza hazard + pendenza ammessa |

Finché superficie, hazard e slope non sono nella pianta, `mission_success` è `not_scored`; non è
lecito chiamare “safe” un contatto morbido a centinaia di metri dal sito.

Il log esistente `t3_s0_scripted` prova un soft touchdown (0.71 m/s verticale e 0.59 m/s
orizzontale), non mission success: è a ~802 m dal target e registra sette safety veto.

---

## 2. Stato iniziale reale del repository

| Componente | Stato | Nota |
|---|---|---|
| yaYUL, yaAGC, Luminary 099 | presente | build e rope sono già automatizzati |
| Bridge AGC | presente | channel socket, DSKY, P27, core dump, PIPA/CDU, discreti |
| Pianta | presente, non 6-DoF | dinamica lunare, DPS, mass flow, IMU, radar, throttle |
| Setup P63 e loop | presente | esiste un soft touchdown registrato con Luminary nel loop |
| Clock, snapshot e recorder | presenti | JSONL gzip, replay e snapshot pre-ignition |
| Velocità | presente | run scripted registrato a ~22.8× real-time |
| Viewer | da sostituire | l'attuale HTML/SSE/Three.js apre un browser e non rispetta il target |
| Policy | null e scripted presenti | seam `Policy → Intent → Executor` pronta |
| LLM | assente | da inserire soltanto dopo il simulatore finito e documentato |
| Metriche | incomplete | il punteggio attuale non impone distanza dal target/hazard/slope |

Non ricostruire AGC bridge, P63, clock, recorder o pianta da zero. Lavorare per completamento e
correzione delle parti mancanti.

---

## 3. Architettura definitiva del simulatore

```text
scenario seed + dispersioni + superficie sintetica
                 │
                 ▼
 pianta LEM ◄── sensori (PIPA/CDU, radar, discreti) ──┐
     ▲                                                │
     │ DPS/RCS                                        ▼
     └──────── yaAGC + Luminary 099 ◄──────── AGC bridge
                                                    │
          ┌─────────────────────────────────────────┴─────────────┐
          ▼                                                       ▼
  observation per policy                                 recorder JSONL
          │                                                       │
  scheduler + executor + safety                              ViewFrame
          │                                                       │
 policy null/scripted/manual (LLM solo dopo)              coda latest-wins
                                                                  │
                                                                  ▼
                                                   finestra desktop nativa
                                                   live o replay offline
```

Regole:

- Solo `sim/clock.py` modifica il tempo simulato. Nessun altro modulo usa `sleep` o wall clock per
  far avanzare la fisica.
- Il renderer è un osservatore: usa una coda bounded e non rallenta mai AGC, pianta o recorder.
- Chiudere la finestra non interrompe l'episodio; `--no-ui` è sempre disponibile per test e batch.
- Il replay legge log, non riesegue AGC/plant/modello e non usa localhost.
- Il safety monitor è un controllore di emergenza separato, non una vittoria dell'agente.

---

## 4. UX nativa: semplice, geek, senza browser

### Tecnologia e struttura

Usare `pygame-ce` con SDL nativo. Non usare browser, `webbrowser`, server HTTP, SSE, WebSocket,
Rerun, Three.js o bundler nel percorso principale.

```text
src/luminary_agent/viz/
  view_model.py       # dataclass ViewFrame; record/log → frame; testabile senza UI
  native_app.py       # event loop pygame, live/replay e input
  native_renderer.py  # layout, telemetria, DSKY, LEM, griglia, trail
  lem_mesh.py         # mesh procedurale originale e parametri dimensionali
  replay.py           # lettura streaming JSONL e timeline; nessun HTML
docs/
  lem-model-sources.md
```

`Simulation` pubblica al massimo 20 `ViewFrame` al secondo di wall time. Il recorder continua a
scrivere ogni tick; un renderer lento perde frame intermedi ma mostra sempre il più recente.
`luminary view LOG` ricostruisce gli stessi `ViewFrame` dal log.

### Finestra

```text
┌──────────────────────────────────┬────────────────────────────────────┐
│ LEM wireframe low-poly originale  │ AGC / DSKY                         │
│ (ascent + descent stage, gear)    │ PROG 63 VERB 06 NOUN 63            │
│          thrust vector            │ R1 ... R2 ... R3 ...               │
│                                  ├────────────────────────────────────┤
│ griglia lunare grigia             │ ALT  V/S  HVEL  THR  FUEL           │
│ target, traiettoria e trail       │ RADAR / AGC ALT / ALARMS            │
│                                   ├────────────────────────────────────┤
│                                   │ MODE / INTENT / VETO / REASON       │
└──────────────────────────────────┴────────────────────────────────────┘
```

- Palette: sfondo quasi nero, griglia grigia, font monospaziato chiaro, un colore caution e uno
  alarm. Niente gradienti, ombre, gauge o decorazione.
- Dati reali: posizione, quota, velocità, spinta, massa, DSKY, allarmi, target, trail,
  intenti e veto. Mesh LEM, griglia e plume sono visualizzazione; ogni semplificazione viene
  dichiarata nella UI e nel README.
- Comandi: `Space` pausa/riprendi la vista, frecce scrubbing replay, `1/2/3` camere,
  `Esc` chiude solo la finestra. Una eventuale pausa della simulazione deve passare dal clock,
  non dall'event loop della UI.

---

## 5. Fasi: simulatore completo prima dell'agente

### Fase S0 — Integrità, metriche e provenienza

1. Rimpiazzare `Score.safe` con `soft_touchdown` e aggiungere `mission_success`/`not_scored`.
2. Riportare sempre errore target, fuel, safety veto, fallback e decision count nella summary.
3. Aggiungere i fingerprint AGC, rope, patch, scenario e codice nell'header JSONL.
4. Spostare la patch free-run in worktree/cache di build oppure dichiarare apertamente il submodule
   modificato e loggarne il diff hash.
5. Aggiornare test unitari per punteggio, provenance e summary.

**Gate S0:** un landing a 802 m può essere `soft_touchdown=true`, ma non `mission_success=true`;
ogni log ha provenance completa; le unit test aggiornate passano.

**Stato S0 (verificato 2026-09-20 sul Mac locale):**
- Punti 1, 2, 3, 5: fatti. `Score` ha `soft_touchdown` + `mission_success` (`not_scored` finché
  `surface_scored=False`); summary/report mostrano target error, fuel, decisioni, safety veto,
  fallback; l'header JSONL contiene `provenance()` (git SHA/dirty, commit VirtualAGC, hash patch,
  hash diff submodule, hash yaAGC, rope, listing, scenario).
- Punto 4: build in worktree/cache (`results/cache/agc`): patch applicata lì, yaAGC e rope
  (`Luminary099/MAIN.agc.bin`) compilati lì. Submodule `external/virtualagc` **pulito**
  (`git status` vuoto; la vecchia patch a mano era identica a `patches/yaagc-free-run.patch`,
  verificato con `cmp` prima del `checkout`). Provenance: `virtualagc_dirty=false`,
  `virtualagc_diff_sha256` = hash di diff vuoto, patch hashate in `patch_set_sha256`.
- Test: `pytest tests/unit` 242 passed; `ruff` e `mypy` puliti; `pytest tests/integration`
  14 passed.
- Non verificato: nessun nuovo episodio end-to-end con la provenance nel JSONL (run da ~20 min non
  eseguito); i log esistenti in `results/runs/` precedono S0 e non hanno i nuovi campi.

### Fase S1 — Completa la pianta e l'interfaccia di simulazione

**Obiettivo:** fare in modo che ciò che Luminary comanda sia traducibile in uno stato del LEM
fisicamente coerente e misurabile prima della grafica finale.

1. Consolidare 3-DoF/laterale esistente: riferimento lunare, gravità, massa, DPS, throttle
   incrementale, sensori PIPA/CDU, discreti, radar lock/dropout e superficie rotante.
2. Per ogni sensore/attuatore, aggiungere test analitico e integration test AGC; segnare unità,
   segni, scaling e canale in `docs/agc-integration.md`.
3. Scegliere esplicitamente il confine MVP: 3-DoF con pitch comandato è sufficiente alla prima
   discesa; 6-DoF/RCS torque non entra finché mancano test frame/attitude.
4. Rendere `NullAgent` e `ScriptedAgent` eseguibili con safety on/off. Stabilizzare lo scripted
   fino a non dipendere da rescue safety per un caso nominale.
5. Completare `mission_success` soltanto quando surface model espone target, hazard e pendenza;
   fino ad allora lasciare il campo non calcolato.

**Gate S1:** da uno stato P63, Luminary guida la pianta fino a soft touchdown in un caso nominale;
canali, PIPA/CDU, throttle, DSKY e log sono osservabili; integration test AGC passano sul Mac locale.

**Stato S1 (verificato 2026-09-20 sul Mac locale, dopo pulizia di `results/logs` e `results/runs`):**
- Punto 1/3: pianta 3-DoF già completa; confine MVP dichiarato in `docs/agc-integration.md`.
- Punto 2: `docs/agc-integration.md` (unità, segni, scaling, canale, test unitario + integration per
  ogni segnale). Il radar NON raggiunge l'AGC (solo osservazione): dichiarato, non modificato.
- Punto 4: tier 1 seed 0, tre run reali con la provenance nell'header: `scripted` con safety on e
  off → soft touchdown, 0.34 m/s verticale, 0.00 orizzontale, 6.8 m dal target, 0 veti, risultato
  identico (nessuna dipendenza dalla safety); `null` → soft touchdown 0.79 m/s, 375 m dal target,
  0 veti. ~21× real-time. `mission_success` = `not_scored` in tutti.
- Punto 5: invariato (`not_scored`, per S2).
- Test: unit 242 passed, ruff/mypy puliti, integration 14 passed. `ruff` ora esclude `results/`.
- Tier 2/3 seed 0 con safety on (run reali): t2 scripted soft, 0 veti, 177 m dal target; t2 null
  soft, 0 veti, 194 m; t3 scripted soft, 4 veti, 801 m; t3 null NON soft (4.5 m/s orizzontale),
  4 veti. Nel tier 3 (100 m di errore d'altitudine) la safety interviene: il risultato non va
  attribuito al solo agente.
- **[SUPERATO in S4: quei run non erano deterministici; usare `results/tables/baselines-dev.md`]** Batteria completa (2026-09-20, safety on, 150 episodi, `results/logs/{dev,frozen}/{null,scripted}`),
  soft touchdown: dev null 8/15, dev scripted 14/15; frozen null 35/60 (T1 20, T2 14, T3 1),
  frozen scripted 40/60 (T1 20, T2 14, T3 6). `mission_success` = `not_scored` ovunque. Tier 1:
  0 veti; tier 3: la safety interviene (mediana 4 veti sul frozen), quindi quei numeri non sono
  attribuibili al solo agente. Molti T3 (vh 150-500 m/s, target km) toccano terra prima del
  takeover dello scripted (150 m): per progetto T3 non è sopravvivibile da Luminary da solo.
- Difetto trovato e **risolto**: ~2 % degli episodi (3/150) andava in timeout 60 s sulla pipe del
  debugger di yaAGC. Causa radice: lost-wakeup in `yaAGC/nbfgets.c` (il thread di input imposta
  `nbfgetsReady`, poi prende il mutex e aspetta; se il main consuma e fa `broadcast` in quella
  finestra, il segnale si perde e il thread non legge più stdin). Riprodotto con una tempesta di
  `STEP 1` su 16 yaAGC paralleli (1/16 bloccato col binario vecchio), corretto in
  `patches/yaagc-free-run.patch` con un predicato sotto mutex. Dopo la correzione: 3 × 16 × 6000
  step senza blocchi, dev set scripted a 8 worker senza ritenti, risultati identici ai precedenti.
  Regressione: `tests/integration/test_stepped_stress.py`. Il ritento in `run_set` resta come rete
  di sicurezza.

**Non fare:** estendere subito a abort, P66, LPD, RCS failure o 1201/1202. Sono capacità separate.

### Fase S2 — Superficie e LEM originale

**Obiettivo:** completare il modello visivo e il terreno minimo, senza compromettere rapidità.

1. Raccogliere fonti dimensionali/prospetti pubblici del LEM e creare `docs/lem-model-sources.md`.
2. Implementare la mesh procedurale originale del LEM con parametri e test di proporzioni/silhouette.
3. Implementare una superficie sintetica seedata: griglia grigia sempre disponibile; hazard e slope
   sono dati della scenario surface e non decorazione casuale.
4. Collegare target, hazard e slope allo scorer solo dopo averli resi parte della pianta.
5. Esporre in log e `ViewFrame` i dati necessari a spiegare perché un touchdown sia/not mission
   success.

**Gate S2:** il LEM visibile è riconoscibilmente Apollo LM e costruito dal codice del repo; la sua
proporzione è verificabile contro fonti documentate; la griglia mostra target e superficie seedata;
un hazard/slope influisce realmente sul punteggio, quando attivato.

**Stato S2 (2026-09-20, sul Mac locale):**
- Punto 1: `docs/lem-model-sources.md` documenta origine (NASA), licenza (da confermare), procedura e
  cosa è/non è verificato. Le dimensioni pubblicate restano `[doc]` non controllate (nessuna rete).
- Punto 1-2 (rivisti dopo il GLB): il modello procedurale a poligoni è stato **sostituito** da una
  mesh a 9 127 triangoli (75 KB, `lem/lem_mesh.npz`) ricavata una volta dal modello NASA
  (https://science.nasa.gov/3d-resources/apollo-lunar-module/, `docs/Apollo Lunar Module.glb`) con
  `lem/glb_mesh.py` (scala a 7.04 m, niente antenne/parabole/dettagli < 5 cm, semplificazione per
  vertex clustering, colore per faccia). Runtime: solo `load_lem_mesh()`, il GLB non viene letto.
  Test `test_lem_mesh.py`: mesh ben formata e < 15k triangoli, suola a z=0, un piede su ciascun
  asse, apertura ≈ 9.0 m, sovrapposizione dei contorni col riferimento (0.93 / 0.90 / 0.99; sotto 1
  perché il riferimento include le antenne), rendering non vuoto. `lem/preview.py` disegna tre viste
  ombreggiate. Ripulito: rimosso il vecchio modello procedurale (`model.py`) e il suo SVG.
  DracoPy serve solo per ricostruire la mesh (`uv run --with DracoPy`), non è in `pyproject`.
- Aperto: **licenza** da incollare da quella pagina NASA in `docs/lem-model-sources.md` (fonte
  NASA indicata dall'utente, non verificabile da qui); **scala assoluta** legata a 7.04 m di altezza
  con conflitto sulla larghezza degli stadi (5.8 m nel modello contro ~4.2 m ricordati); le
  dimensioni pubblicate restano `[doc]` non controllate. La *forma* è quella NASA.
- Punto 3: `plant/terrain.py`, `Surface.sample(seed)`: bersaglio libero e piatto entro 30 m, 150
  crateri + 500 massi + 30 rilievi gaussiani entro ±2.5 km; `grid()` per il renderer S3. Su punti a
  caso entro 1 km: ~3.5 % ostacolo, ~1.6 % pendenza > 12°.
- Punto 4: `score(result, dry, surface)`; `mission_success` = soft ∧ bersaglio ≤ 100 m ∧ senza ostacolo
  ∧ pendenza ≤ 12°. `run_episode` usa la superficie di default (`--no-surface` → `not_scored`).
  Lo scorer vede anche l'errore laterale (prima solo down-range). Hazard e pendenza cambiano il
  verdetto: test unitari e, sul landing reale dev scripted t1_s0 (6.8 m dal bersaglio), un masso o
  una pendenza piazzati sotto il punto d'arrivo lo rendono `mission_success=false`.
- Punto 5: header `surface` + riga finale `landing` (`read_landing`) con score e assessment.
  `ViewFrame` non esiste ancora (è S3): i dati sono nel log, da leggere lì.
- Test: 270 passed (unit + integration), ruff/mypy puliti (dopo la mesh: `pytest tests`).
- **[SUPERATO in S4: quei run non erano deterministici; usare `results/tables/baselines-dev.md`]** Dev set (15 episodi/policy, safety on, surface on, 0 stalli): null soft 8/15, mission_success
  0/15; scripted soft 14/15, mission_success 8/15 (T1 4/5, T2 3/5, T3 1/5). I 6 soft-non-mission
  dello scripted falliscono per distanza dal bersaglio (1 anche per ostacolo). Nessun caso reale
  deciso da solo da ostacolo/pendenza: succede solo con sito sfavorevole.
- Limiti dichiarati: contatto fisico ancora sul piano a quota 0 (la superficie non altera la
  dinamica); soglia 12° e raggio del piede sono giudizio ingegneristico da verificare; il gate S2
  "LEM riconoscibilmente Apollo LM" (l'utente deve approvare il preview) e "proporzione verificabile
  contro fonti" (checklist in `docs/lem-model-sources.md`) restano **aperti**.

### Fase S3 — Finestra nativa live/replay

1. Aggiungere `pygame-ce`, ViewFrame e renderer nativo.
2. Collegare UI live al loop con coda latest-wins, senza cambiare recorder o clock.
3. Disegnare LEM, griglia, trail, target, thrust, DSKY, telemetria, allarmi e stato policy/safety.
4. Implementare lo stesso renderer per replay JSONL offline con scrubbing.
5. Rimuovere da `luminary fly` e `luminary view` apertura browser, HTTP server e SSE. Il viewer HTML
   può restare temporaneamente non documentato solo per debug, poi verrà eliminato.

**Gate S3:** da clone pulito, `make agc && uv run luminary fly --tier 3 --seed 0 --policy scripted`
apre una sola finestra nativa, mostra una discesa con DSKY live, salva il JSONL e termina con un
verdetto chiaro. `uv run luminary view LOG` riproduce lo stesso episodio senza browser, AGC,
Ollama o server localhost.

**Stato S3 (2026-09-21, sul Mac locale):**
- Punto 1-3: `pygame-ce` (in `pyproject`), `viz/view_model.py` (`ViewFrame`, `FrameBuilder`),
  `viz/native_renderer.py`, `viz/native_app.py`. Finestra 1280×720: scena (mesh LM NASA con l'assetto
  del plant, pennacchio ∝ spinta, griglia con tinta di pendenza, bersaglio con anelli 30/100 m,
  crateri e massi seedati, scia), profilo della discesa, quota vera/radar/AGC (ultimi 200 s), DSKY con
  spie ENGINE/MANUAL/ALARM, telemetria, stato della politica (modo, decisione, motivo, veto),
  verdetto e legenda "reale / disegnato / 3-DoF". Tre camere (1/2/3), pausa della vista, scrubbing,
  velocità 0.5×–60×.
- Punto 2 (live) — **scoperta**: una finestra nello stesso processo (anche in un thread) rallenta la
  discesa di ~5× (209 s invece di 45 s): la simulazione è una catena di piccoli scambi con l'emulatore
  (limitata dalla latenza) e il thread di disegno tiene il lock dell'interprete a fette. Soluzione: la
  discesa gira in un **processo separato** e manda i frame su una coda limitata (`viz/live.py`,
  `LiveFeed`/`LiveReader`, latest-wins). Misurato (tier 3 seed 0 scripted, finestra headless): 18.8×
  il tempo reale, 27 fps di disegno, 43.7 s in tutto. Chiudere la finestra non ferma l'episodio;
  `--no-ui` esegue senza finestra.
- **Bug preesistente trovato e corretto**: `run_episode` accettava `live` ma non lo passava a
  `run_descent`; il vecchio viewer live non riceveva nulla. Ora sì (`live=live`).
- **Bug di prestazioni trovato e corretto**: `pygame.draw.line` con segmenti tagliati al piano vicino
  (estremi a milioni di pixel) costava 3 ms a linea → 1.6 s a frame; ora si clippa prima
  (`Rect.clipline`): 23 ms a frame (~40 fps).
- Punto 4 (replay): `luminary view LOG` legge il log (`viz/replay.py`, 10 Hz) senza AGC, emulatore,
  Ollama, browser o localhost; `--screenshot out.png --at T --camera N` per un PNG senza finestra.
  A fine episodio la finestra live passa da sola al replay del log a piena risoluzione.
- Punto 5: rimossi `viz/replay3d.html`, `viz/vendor/three.min.js`, il server HTTP/SSE, `webbrowser`, la
  generazione degli `.html` in `run_set`. `luminary fly --no-view` è diventato `--no-ui`.
- Test: 292 passed (unit + integration), ruff e mypy puliti. Nuovi: `test_view_model`, `test_replay`,
  `test_live_feed` (incl. attraverso un processo `spawn`), `test_native` (SDL dummy: tutte le camere,
  cache degli sprite, `Player`, verdetto, ciclo eventi, screenshot).
- Verificato end-to-end **headless** (driver SDL dummy) con il vero percorso di `luminary fly --tier 3
  --seed 0 --policy scripted`: DSKY live, verdetto "SOFT TOUCHDOWN - NOT MISSION SUCCESS" (816 m dal
  bersaglio), log salvato. **Non verificato a occhio**: una finestra reale sul display del Mac
  (aspetto, fluidità, tasti) e `make agc` da clone pulito; la verifica interattiva va fatta a mano.
- Limiti dichiarati: pitch/assetto solo nel piano (nessuna rotazione laterale disegnata); la scena a
  400 km dal bersaglio mostra soprattutto il LM e la scia (la vista utile ad alta quota è il profilo);
  la mesh è una semplificazione del modello NASA (licenza da confermare, vedi S2).

### Fase S4 — Scenari, baseline e accettazione del simulatore

Scenari iniziali, perché sono già osservabili e influenzabili dalle azioni disponibili:

- errore di stato iniziale rivelato dalla discrepanza radar/AGC;
- dropout/bias radar;
- degradazione DPS e riduzione margine propellente;
- dispersioni massa e spinta;
- target, pendenza e hazard della superficie seedata.

Per ciascuno servono: seed, parametro, osservabile, azione disponibile, fonte, expected outcome e
test. Non introdurre un evento che l'equipaggio non può leggere o modificare.

Baseline richieste: `NullAgent`, `ScriptedAgent`, safety on/off; PID/MPC solo se serve a isolare un
limite del ManualController. Il batch usa 15 episodi dev (3 tier × 5 seed); i 60 frozen arrivano
dopo l'agente.

**Gate S4 — SIMULATORE COMPLETO:**

- `luminary fly`, `--no-ui`, `view` ed `eval` funzionano da clone pulito;
- la finestra nativa usa il LEM originale del repo e non il browser;
- un log può essere spiegato solo con UI + JSONL, senza AGC in esecuzione;
- baseline producono tabella con soft touchdown, mission success/not scored, target error, fuel,
  decisioni e safety; `NullAgent` fallisce almeno alcuni casi duri;
- 100% dei test unitari e integration AGC passano localmente;
- limiti espliciti 3-DoF/6-DoF, azioni non supportate e differenza dati reali/cosmetici sono visibili.

L'agente LLM non inizia prima del Gate S4.

---

**Stato S3 — aggiornamento (2026-09-21):** la finestra è stata **approvata dall'utente a vista**
("astonishing and beautiful"). Due ritocchi richiesti e fatti: la superficie è sempre visibile (piano
grigio scuro con griglia e orizzonte, a qualunque quota) e la camera resta a **32 m** dal LM (prima
si avvicinava con la quota). Resta non verificato solo `make agc` da clone pulito → **fatto in S4/DOC**
(sotto).

### Stato S4 (2026-09-21, sul Mac locale)

- **Scenari** → `docs/scenarios.md`: cinque scenari (S-1 errore di stato, S-2 radar bias/dropout,
  S-3 degradazione DPS, S-4 massa/spinta/propellente, S-5 superficie) con seed/manopola, osservabile,
  azione disponibile, fonte (con etichette rope/measured/doc), esito atteso e test. Per rispettare
  "nessun evento che l'equipaggio non può leggere" **`Observation` ora include il bersaglio (sotto
  3 000 m) e pendenza/ostacoli (sotto 500 m)**: prima l'agente non poteva vedere cosa decide
  `mission_success`. `flight-contexts.md` aggiornato (superficie non più "non modellata").
- **Scoperta grave: il volo non era deterministico.** Cinque copie dello stesso episodio in parallelo
  davano 2-3 risultati diversi (1.60 / 2.58 / 0.76 m/s); batch con monitor acceso e spento non
  coincidevano nemmeno senza veti. Causa: yaAGC è pilotato su due canali non ordinati (pacchetti TCP e
  comandi sulla pipe) e l'ordine d'arrivo dipendeva dallo scheduling. Correzione in due barriere
  (`patches/yaagc-free-run.patch` + `agc/handshake.py`): `STEP n B` attende i B byte inviati dal
  client; un marcatore (canale 0377) sul socket prima del prompt garantisce che il client abbia letto
  tutto l'output del comando. Verifica: 4 round × 5 copie affiancate (tier 2 seed 1) e 1 round × 5
  (tier 3 seed 2) → risultati identici; un test d'integrazione (`test_determinism.py`, 6 copie, cycle
  counter identici) fallisce col vecchio comportamento ~1 volta su 4 e passa col nuovo; velocità
  invariata (~20× il tempo reale). Le baseline sono state rigenerate dopo la correzione.
- **Baseline** (`results/tables/baselines-dev.md`, 15 episodi dev × {null, scripted} × {safety on,
  off}, deterministiche): null soft 5/5 · 3/5 · 0/5 (tier 1-3), mission 0/15; scripted soft 14/15,
  mission 8/15 (4/5, 3/5, 1/5). **`NullAgent` fallisce i casi duri** (tier 3: 0/5, propellente
  mediano 0). Negli episodi senza veti safety on/off è identico bit a bit (9/9 null, 13/13 scripted);
  i veti (13 in 6 episodi null, 5 in 2 scripted) non cambiano nessun atterraggio morbido.
- **Gate S4**: `luminary fly` (finestra, provata con driver SDL dummy dal vero percorso CLI e a vista
  dall'utente), `--no-ui`, `view` (anche `--screenshot`) ed `eval` (usato per le baseline) funzionano;
  la finestra usa la mesh NASA del repo, non il browser; un log si spiega con UI + JSONL (`view` senza
  AGC); limiti 3-DoF, azioni non supportate e reale/disegnato sono nella legenda della finestra;
  **296 test** (unit + integration AGC) passano localmente, `ruff` e `mypy` puliti.
  **Aperti, dichiarati**: licenza del modello NASA da incollare in `docs/lem-model-sources.md`; le
  dimensioni pubblicate del LM restano `[doc]` non controllate; il set frozen (60) non è stato
  rieseguito dopo la correzione del determinismo (i vecchi log dei 150 episodi della Fase S1 non sono
  più riproducibili bit a bit e non vanno citati).

### Stato DOC (2026-09-21)

- `README-simulator.md` riordinato secondo §6: indice per scopo, **A** requisiti (rete solo per
  l'installazione), **B** setup, **C** primo volo con tre immagini reali (`docs/img/`), **D**
  replay/batch/snapshot/`--no-ui`, poi glossario, mappa, percorso della discesa, fisica, LM,
  superficie/punteggio, log/provenienza, **T** troubleshooting, limiti, file per file.
- **Test di lettura in directory pulita** (eseguito): `git clone --recurse-submodules` di una copia
  del repo (sottomodulo locale, senza rete), poi esattamente `make setup` (2 s) → `make agc` (15 s) →
  `make test` (**296 passed** in 55 s) → `luminary fly --no-ui --tier 3 --seed 0 --policy scripted`
  (45 s totali compresa la costruzione dello snapshot, ~10 s): risultato **identico al repo di
  lavoro** (0.72 m/s, 816 m, 4 veti, 763 decisioni) → riproducibilità tra directory. Il percorso con
  finestra (driver dummy) e `luminary view --screenshot` funzionano dal clone. Correzioni emerse:
  lo snapshot costa ~10 s, non ~2 min; `VIRTUAL_ENV` ereditato da un'altra shell dà solo un avviso di
  `uv`. Limite: "pulito" = copia dell'albero di lavoro non committato, con un submodule locale; il
  vero `git clone` da GitHub e il download di dipendenze da PyPI non sono stati esercitati (nessuna
  rete usata in quel test dopo `uv sync`, che è avvenuto con la cache locale).
- Fingerprint (log di `t1_s0_scripted`): VirtualAGC `45bd7333…` pulito; yaAGC `45d1df8c…`; rope
  `1f5326e0…`; listing `b12cdfe4…`; patch set `59fb264f…`; build in worktree di cache.

---

## 6. README-simulator: deliverable obbligatorio dopo il simulatore

Il README non è una nota breve: è il manuale di esecuzione e lettura del progetto per una persona
che non conosce AGC, P63, yaAGC, PIPA, socket channel o il codice esistente. Va scritto **dopo S4**,
quando i comandi e l'architettura sono stabili; non cancellare l'attuale documento finché la nuova
versione non sia verificata su clone pulito.

`README-simulator.md` deve contenere, in quest'ordine:

1. cosa fa il simulatore, cosa è realmente AGC e cosa è modellato localmente;
2. requisiti macOS, strumenti e spazio disco; differenza tra esecuzione offline e installazione
   iniziale delle dipendenze;
3. setup da clone pulito, riga per riga, spiegando che cosa fa ogni comando;
4. primo volo con `luminary fly`, significato della finestra e lettura del verdetto;
5. replay, batch eval, snapshot e `--no-ui`;
6. mappa del repository e percorso completo di una discesa: CLI → AGC → bridge → pianta → sensori
   → UI/log;
7. spiegazione semplice di AGC, Luminary, DSKY, P63, PIPA/CDU, discreti, DPS e clock stepped;
8. descrizione della fisica, delle unità, frame, sensori e semplificazioni attive;
9. modello LEM: fonti, processo di generazione originale, cosa è fedele e cosa è schematico;
10. superficie, target, hazard, score e differenza tra soft touchdown e mission success;
11. schema dei log JSONL, provenance e come riprodurre un episodio;
12. test unitari/integration, come interpretare failure dovuti a porte sandboxate;
13. troubleshooting pratico: build, porte, snapshot, modello assente, UI che non si apre;
14. limiti correnti e capacità Apollo volutamente non ancora supportate.

Il README deve usare diagrammi ASCII semplici, esempi di output reali e link ai file del repo. Ogni
termine tecnico va definito alla prima occorrenza. Nessun comando implicito, nessun “ovviamente”.

**Gate DOC:** una persona che parte da clone pulito riesce a buildare, eseguire, osservare, fare
replay e capire la catena dati seguendo soltanto il README. Il test di lettura va eseguito in una
directory pulita e le correzioni confluiscono nel documento prima di iniziare l'LLM.

---

## 7. Agente locale, solo dopo S4 e DOC

### Interfaccia fissa

Il modello riceve un brief deterministico derivato da `Observation` e restituisce solo:

```json
{
  "action": "hold | take_manual | set_manual_target",
  "vertical_rate_mps": -1.0,
  "horizontal_velocity_mps": 0.0,
  "reason": "radar and AGC altitude disagree; take manual control"
}
```

Validazione deterministica:

- enum chiuso, tipi e range fisici;
- reason massimo 240 caratteri, solo debug/timeline;
- `set_manual_target` rifiutato prima del takeover;
- LLM non sceglie il TTL: scheduler assegna 3–10 s e heartbeat di 10 s;
- evento (programma, allarme, modo, radar) risveglia subito la policy;
- timeout/JSON invalido/backend morto → ultimo intent breve, poi `ScriptedAgent`, loggando il
  fallback.

La simulazione mette in pausa pianta e AGC mentre `decide()` attende. Il report separa
`decision_wall_latency_s` da `sim_time_while_thinking_s`, che deve essere zero.

### Fase A1 — Integrazione LLM

1. backend locale con health check, timeout e nessuna rete esterna;
2. prompt versionato, schema JSON, parser, clamp e fallback testati;
3. provenance di modello, digest e prompt nell'header;
4. UI mostra richiesta, applicazione, reason, latenza, veto e fallback;
5. test di JSON malformato, timeout e modello assente.

**Gate A1:** tier 1 seed 0 termina senza JSON invalido/fallback, con reason visibile e ≤120 chiamate
modello.

### Fase A2 — Primo confronto utile

Sul dev set 15 episodi produrre almeno queste tabelle separate:

- LLM + safety;
- LLM senza safety;
- scripted + safety;
- scripted senza safety;
- null + safety e null senza safety quando sensato.

Metriche: soft touchdown, mission success/not scored, errore target, hazard/slope outcome, fuel,
numero decisioni, wall latency, veto, fallback. Un atterraggio salvato dalla safety non è attribuito
al solo LLM.

---

## 8. Lavoro futuro dopo l'agente MVP

1. completare citazioni `docs/flight-contexts.md` con pagina/sezione verificata;
2. indurre 1201/1202 attraverso carico/interruzioni reali, non un display finto;
3. introdurre 6-DoF, RCS e guasti solo dopo test di assetto/frame;
4. integrare MARKRUPT/P66/LPD quando esistono interrupt path, pad load e azioni verificabili;
5. modellare ascent stage prima di dichiarare abort;
6. congelare 60 episodi, bootstrap CI, realtime contro stepped e `make reproduce`;
7. aggiungere reflection/memory/self-consistency solo se il benchmark mostra un difetto che possono
   correggere.

---

## 9. Comandi del simulatore finito

```bash
make setup
make agc
uv run luminary snapshot
uv run luminary fly --tier 3 --seed 0 --policy scripted
uv run luminary fly --tier 3 --seed 0 --policy scripted --no-ui
uv run luminary view results/runs/t3_s0_scripted.jsonl.gz
uv run luminary eval --set dev --policy scripted
```

Comportamento:

| Comando | Risultato |
|---|---|
| `luminary fly` | una finestra nativa, un log JSONL e un verdetto |
| `luminary fly --no-ui` | run headless per test/batch |
| `luminary view LOG` | replay nella stessa UI, senza AGC/modello/server |
| `luminary eval` | batch senza UI e tabella da log |
| `luminary agc build` | build AGC/rope e stampa fingerprint |

---

## 10. Verifica dei gate

### Test automatici

```bash
uv run pytest tests/unit -q
uv run ruff check src tests
uv run mypy
uv run pytest tests/integration -q
```

Gli integration test richiedono socket localhost. Se un sandbox blocca `127.0.0.1`, non trattare il
fallimento come regressione del bridge: rieseguirli sul Mac locale prima di segnare S1/S4 come passati.

### Smoke test UI

1. Da clone pulito buildare AGC e snapshot.
2. Avviare `luminary fly` senza browser.
3. Verificare DSKY, quota/spinta, trail, LEM/griglia, target, intenti e veto.
4. Chiudere la finestra: l'episodio e il log devono completare senza crash.
5. Aprire il log con `luminary view`: nessun yaAGC, Ollama o server locale deve essere necessario.

---

## 11. Rischi e fallback

| Rischio | Azione |
|---|---|
| UI rallenta il loop | coda latest-wins, renderer isolato, recorder indipendente |
| Mesh LEM troppo costosa | mantenere wireframe/flat low-poly e fonti dimensionali; non ridurre a lander generico |
| Safety salva una policy debole | risultati on/off e baseline senza rescue prima dell'LLM |
| Patch rompe la riproducibilità | worktree/cache separato, hash e integration test |
| Score sopravvaluta un atterraggio | separare soft touchdown e mission success |
| Scope creep 6-DoF/LPD/abort | prima osservabile → azione → metrica → scenario |
| AGC loop non chiude | fallback guidance Python è modalità separata, mai chiamata “vero AGC” |

---

## 12. Checklist di handoff

Prima del gate successivo aggiornare README/artefatti con:

- comando esatto, OS e risultato;
- fingerprint AGC/rope/patch;
- log JSONL e screenshot della finestra nativa;
- metriche `soft_touchdown` e `mission_success` separate;
- policy e safety mode;
- semplificazioni attive e limiti.

Se una frase non è sostenuta da log, test o fonte tecnica, etichettarla come ipotesi e non come
risultato.
