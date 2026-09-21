# Scenari del simulatore (Fase S4)

Ogni scenario è una **manopola** di `scenarios/dispersions.py` o della superficie seedata
(`plant/terrain.py`), scelta soltanto se l'equipaggio può **leggerne** il sintomo e **cambiarne**
l'esito con un'azione che il simulatore supporta oggi (regola di S4: nessun evento che l'equipaggio
non può leggere o modificare). Le manopole sono deterministiche: `sample(seed, tier)` e
`Surface.sample(seed)` con lo stesso seme danno la stessa cosa (test sotto).

Etichette delle fonti, come in `flight-contexts.md`: **[rope]** verificato nel codice Luminary del
sottomodulo, **[measured]** misurato in questo repository, **[doc]** fonte pubblica *nominata ma non
controllata* (nessuna rete). Un'affermazione `[doc]` è una pista, non un'evidenza.

Azioni disponibili oggi (`policies/base.py`): `hold`, `take_manual` (irreversibile),
`command(descent_rate_ms, horizontal_ms)`. Niente ROD/P66, LPD, abort, RCS, 1201/1202
(`docs/flight-contexts.md` §2.9).

## Tabella degli scenari

| # | Scenario | Seed / manopola | Osservabile (per l'agente) | Azione disponibile | Fonte | Esito atteso | Test |
|---|---|---|---|---|---|---|---|
| S-1 | **Errore di stato iniziale**: il plant parte diverso da ciò che l'AGC crede; l'AGC non lo scopre mai | `Dispersion.dh0_m`, `dvt0_ms`, `dvh0_ms` (tier 1: 0 m / 0.005 m/s; tier 2: ±10 m / 0.02; tier 3: ±100 m / 0.3) | quota radar vs quota AGC (`Observation.radar_altitude_m`, `agc_altitude_m`, DSKY N63/N64 R3) che divergono | `take_manual`, poi `command(descent_rate_ms=…)` guardando il radar | **[measured]** ~700 m di errore in avanti per ogni m/s di errore radiale (`flight-contexts.md` §2.1); **[doc]** l'equipaggio dell'Apollo 11 accettò una grossa discrepanza LR/calcolatore | Luminary da solo non recupera (null, tier 3: 0/5 soft); chi prende il controllo guardando il radar sì | `test_dispersions.py`, `test_manual_control.py`, `test_agent_interface.py` |
| S-2 | **Radar: bias e dropout**: quota radar sbagliata di poco, e in tier 3 assente su una banda di 150–250 m | `Dispersion.radar` (bias ±1 %·tier, rumore 0.5 % + 1 m; tier 3: banda senza aggancio dentro 100–400 m) | `radar_altitude_m` = `None` durante il dropout; il resto del tempo scarto dalla quota AGC | `hold` (fidarsi dell'AGC) o `command` con la sola quota AGC; il monitor di sicurezza usa l'AGC quando manca il radar | **[doc]** aggancio tardivo/dropout del radar nelle missioni 11–15 (da verificare); **[rope]** discreto `ch33` bit 6 (posizione antenna) | il ManualController non deve dipendere da una lettura assente; senza radar il monitor giudica con la quota AGC | `test_radar.py`, `test_safety.py` |
| S-3 | **Degradazione DPS in volo**: il motore perde spinta a metà approccio; l'AGC compensa alzando il gas e non lo segnala | `Dispersion.thrust_fault_at_s` ∈ [620, 900] s, `thrust_fault_scale` (tier 2: ≥ 0.94; tier 3: ≥ 0.85) | `thrust_n` alto per la stessa accelerazione, propellente che scende più in fretta; nessun allarme | `take_manual` presto e scendere diretto costa meno propellente che lasciar librare Luminary | **[doc]** dispersioni prestazionali del DPS (`flight-contexts.md` §2.2); il meccanismo dell'AGC che compensa è **[measured]** | il margine di propellente si riduce; in tier 3 mediana di propellente 0 senza intervento | `test_dispersions.py` (guasto in finestra e limitato), `test_propulsion.py` |
| S-4 | **Dispersioni di massa, spinta e propellente** | `thrust_scale` (±0.5/1.5/3 %), `mass_scale` (±1/3/5 %), `propellant_scale` (fino a −2/−8/−16 %) | `thrust_n`, `mass_kg`, `propellant_kg` | stesse azioni di S-3: quando prendere il controllo, quanto scendere piano | **[measured]** la massa AGC (pad load) è 6 804 kg contro ~8 100 kg veri; **[doc]** Apollo 11 atterrò con ~25 s di propellente (`flight-contexts.md` §2.2) | il propellante residuo è la metrica; il motore si spegne a propellante esaurito | `test_dispersions.py`, `test_propulsion.py`, `test_score.py` |
| S-5 | **Superficie: bersaglio, pendenza, ostacoli** | `Surface.sample(seed)`: bersaglio libero e piatto entro 30 m; 150 crateri, 500 massi, 30 rilievi entro ±2.5 km | sotto 3 000 m: offset dal bersaglio; sotto 500 m: pendenza sotto il LM e ostacoli entro 250 m (`Observation.target_*`, `slope_here_deg`, `hazards_near`) | `command(horizontal_ms=…)` per spostare il punto di contatto (la ridesignazione LPD resta bloccata) | limiti bersaglio ≤ 100 m, pendenza ≤ 12°: **giudizio ingegneristico** da verificare; **[doc]** criteri di atterraggio ≤ 12° di inclinazione su ≤ 6° di pendenza | `mission_success` = soft ∧ bersaglio ∧ senza ostacolo ∧ pendenza ok; il fallimento più frequente è la distanza dal bersaglio | `test_terrain.py`, `test_score.py`, `test_agent_interface.py` (vista della superficie) |

## Cosa non è uno scenario (e perché)

Non compaiono qui perché l'equipaggio non avrebbe un'azione supportata (`flight-contexts.md`):
1201/1202 (non inducibili), guasto RCS (nessuna dinamica d'assetto), ridesignazione LPD e P66
(bloccati: niente interrupt MARKRUPT sul socket, mancano pad load originali), abort (nessuno stadio
di risalita), polvere sotto i 30 m (sensore non modellato).

## Determinismo (requisito per confrontare)

Uno scenario è confrontabile solo se lo stesso seme dà lo stesso volo. Fino a S3 non era così: 5
copie dello stesso episodio in parallelo davano 2–3 risultati diversi (es. 1.60 / 2.58 / 0.76 m/s di
velocità verticale) perché i pacchetti TCP e i comandi sulla pipe arrivavano a yaAGC in ordine non
garantito. Corretto in S4 (`agc/handshake.py`, `patches/yaagc-free-run.patch`): 20 episodi
identici affiancati danno 20 risultati identici; `tests/integration/test_determinism.py` lo
verifica.

## Risultati delle baseline

Set di sviluppo (15 episodi = 3 tier × 5 seed), safety monitor acceso e spento, policy `null`
(Luminary da solo) e `scripted` (prende il controllo sotto i 150 m di radar o in P65).
Tabella generata da `python -m luminary_agent.eval.report --compare results/logs/dev`, salvata in
`results/tables/baselines-dev.md`.

| config | tier | n | soft touchdown | mission success | median target m | median fuel kg | median decisions | median vetoes | median fallbacks |
|---|---|---|---|---|---|---|---|---|---|
| null | 1 | 5 | 5/5 | 0/5 | 343 | 525 | 961 | 0 | 0 |
| null | 2 | 5 | 3/5 | 0/5 | 215 | 181 | 935 | 0 | 0 |
| null | 3 | 5 | 0/5 | 0/5 | 825 | 0 | 1046 | 2 | 0 |
| null-nosafety | 1 | 5 | 5/5 | 0/5 | 343 | 525 | 961 | 0 | 0 |
| null-nosafety | 2 | 5 | 3/5 | 0/5 | 215 | 181 | 935 | 0 | 0 |
| null-nosafety | 3 | 5 | 0/5 | 0/5 | 885 | 0 | 1046 | 0 | 0 |
| scripted | 1 | 5 | 5/5 | 4/5 | 40 | 790 | 892 | 0 | 0 |
| scripted | 2 | 5 | 5/5 | 3/5 | 55 | 469 | 893 | 0 | 0 |
| scripted | 3 | 5 | 4/5 | 1/5 | 518 | 582 | 888 | 0 | 0 |
| scripted-nosafety | 1 | 5 | 5/5 | 4/5 | 40 | 790 | 892 | 0 | 0 |
| scripted-nosafety | 2 | 5 | 5/5 | 3/5 | 55 | 469 | 893 | 0 | 0 |
| scripted-nosafety | 3 | 5 | 4/5 | 1/5 | 518 | 582 | 888 | 0 | 0 |

Lettura:

- **`NullAgent` falla i casi duri, come richiesto**: tier 3 0/5 atterraggi morbidi (propellente mediano
  0: senza intervento Luminary consuma tutto o arriva veloce), tier 2 3/5. In tier 1 atterra 5/5 ma a
  ~340 m dal bersaglio: un contatto morbido lontano **non** è un successo di missione (0/15 in
  tutte le configurazioni null).
- **`ScriptedAgent`** (prende il controllo guardando il radar): 14/15 morbidi e 8/15 successi di
  missione (tier 1: 4/5, tier 2: 3/5, tier 3: 1/5). Il fallimento dominante è la distanza dal
  bersaglio, non ostacoli né pendenza: scripted non usa `target_*` né `hazards_near`, e questo è il
  margine che un agente può migliorare (`command(horizontal_ms)`).
- **Il monitor di sicurezza non altera nulla dove non interviene**: negli episodi senza veti, con
  monitor acceso e spento il risultato è identico bit a bit (9/9 null, 13/13 scripted). I veti
  sono 13 in 6 episodi `null` (tier 2 e 3) e 5 in 2 episodi `scripted` (tier 3); con o senza monitor gli
  atterraggi morbidi sono gli stessi (null 8/15, scripted 14/15): nessun esito di questa tabella
  è dovuto al monitor. Un risultato ottenuto
  con veti va sempre confrontato con `--no-safety` prima di attribuirlo alla policy.
- **Cosa non dimostra**: 15 episodi non sono il set congelato (60) e non misurano un LLM; i tier
  sono manopole del simulatore, non statistiche di missioni reali.
