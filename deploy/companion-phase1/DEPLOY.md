# Fase 1 deploymentpakket

Dit pakket installeert alleen de Companion-login op de bestaande productiesite. Het zet `IRONKEEP_COMPANION_AUTH` niet aan. Het bevat geen attendance-upload, geen database en geen inhoud van `/etc/ironkeep.env`.

Kopieer niet de map `production/ironkeep/` en niet de hele git-branch naar `/opt/ironkeep`. De branch `cursor/companion-oauth-phase1-f675` heeft als git-basis `cursor/wpf-startup-crash-f675`. Die basis is alleen de reviewgeschiedenis. Dit pakket is gemaakt tegen de productiesnapshot waarvan de zes SHA-256-hashes al op de server kloppen. De patch en de twee nieuwe bestanden importeren niets uit de Windows Companion en niets uit de commits van die WPF-branch.

## Bestanden in dit pakket

| Bestand in het pakket | Doel op de server |
|---|---|
| `phase1-production.patch` | Gerichte wijziging van de zes bestaande bestanden |
| `new/companion_auth.py` | `/opt/ironkeep/ironkeep/companion_auth.py` |
| `new/templates/companion_connect.html` | `/opt/ironkeep/ironkeep/templates/companion_connect.html` |
| `MANIFEST.txt` | Verwachte hashes vóór en ná |
| `install.sh` | Dry-run of installatie |
| `check_imports.py` | Importcontrole zonder productiedatabase |
| `DEPLOY.md` | Deze procedure |
| `test_install.sh` | Alleen lokaal. Niet naar de server kopiëren. |

`install.sh` draait als root. Het weigert een map die geen Ironkeep-package is, een afwijkende SHA-256, of een bestaand Companion-bestand met een andere inhoud. Een dry-run schrijft niets. Een installatie die halverwege mislukt zet de zes oorspronkelijke bestanden terug, inclusief eigenaar, groep en rechten, en verwijdert alleen Companion-bestanden die deze run zelf heeft aangemaakt. `IRONKEEP_COMPANION_AUTH` wordt niet gezet.

## Manifest

Hashes van de oorspronkelijke snapshot, daarna de hashes na een geslaagde installatie. `install.sh` vergelijkt de live bestanden met de eerste kolom voordat de patch wordt toegepast.

| Doel, relatief aan `/opt/ironkeep/ironkeep` | Oorspronkelijk | Na installatie |
|---|---|---|
| `config.py` | `dd8ad682b5f3f8afbec9d38c74ac5b50bca94b5a53914e259d53ba6cd5e6215c` | `c4d2c0b7880da10392c90dcae5c910242371dd0b56e1e06f9d4f2f301fb192e3` |
| `discord_api.py` | `23146ed98ce10496ff6d46a81ee0aaf223f31a632ba1977245e441055aa7326c` | `7f14807660bb36fc7b006da4f96505ae23b4896cc80c3f386aa16288731b3349` |
| `db.py` | `58410203956e197e00666486b2a1fa6db9a0092ec350386bbeb901ef5e47ba87` | `74f41dbc2c55f87143ad37fa987e8c35657ab8e325611dc36c53f6948b9cae54` |
| `main.py` | `3a5783a13b148fd88ec624b7a5b27b8e84789311481c5ec12f6f5537a5183c2e` | `f527479bb12ba29fe296504360191f79885db62c4cd4704aca9dcd5077c8c126` |
| `templates/settings.html` | `c78de62594d5f328539bb52b45f0ce7c7b1577f18be67c9979ace79914329f88` | `3259370864f7a562dc62c66e183d3a6bc5269acb9ba174a529a6ab57e4ec95a0` |
| `static/js/settings.js` | `ac9b1b3cc840ffb0474fb3a6f652b32ba57e78ab41a0391bb6fcf3d0502afe0f` | `01b861d4118481748d52f5803cf8ff52d1814b76894d4f1f0a9a9fd0c29b6cf2` |
| `companion_auth.py` | bestaat nog niet | `b4663dee4810ef5b3382c906d863894cbd0c9492cd5348711812c9a548b86581` |
| `templates/companion_connect.html` | bestaat nog niet | `db329c7d460462dba6efd5d7bf07212e584e84e15e2495eee31914c4c07eec9d` |

## Imports van de Companion-module

`companion_auth.py` importeert de standaardbibliotheek, FastAPI, en `config`, `db` en `discord_api`. `SESSION_COOKIE`, `render` en `_secure` komen pas bij een verzoek uit `main`, en die drie bestaan al in de oorspronkelijke `main.py`.

De patch voegt alleen toe: `config.companion_auth_enabled`, `discord_api.member_as_bot` en `db.companion_role_ids`. `discord_api.bot_member(guild_id)` blijft de bestaande functie die tickets gebruikt. De module importeert `wow`, `tickets`, `forever_companion`, `warcraft_forever` en `albion` niet, en heeft geen attendance-route.

## Dry-run

Zet het pakket bijvoorbeeld in `/home/ironadmin/companion-phase1-package`. Voer dit uit op de server:

```bash
sudo bash /home/ironadmin/companion-phase1-package/install.sh --root /opt/ironkeep/ironkeep
```

Verwacht: `original ok` voor de zes bestanden, `patch dry-run ok`, en `Dry run finished. No files were written.` De dry-run controleert ook dat de gebruiker `ironkeep` de bestaande bestanden kan lezen en de doelmap kan doorlopen. Er wordt niets aangemaakt of gewijzigd.

## Installatie

```bash
sudo bash /home/ironadmin/companion-phase1-package/install.sh \
  --root /opt/ironkeep/ironkeep \
  --apply \
  --backup-dir /home/ironadmin/companion-phase1-files-20261105
```

Dit kopieert de zes huidige bestanden naar de backup-map, past de patch toe en zet de twee nieuwe bestanden neer met dezelfde eigenaar, groep en rechten als `config.py`. Daarna controleert het dat `ironkeep` `companion_auth.py` en `templates/companion_connect.html` kan lezen. Mislukt een stap na de eerste wijziging, dan worden de zes bestanden uit de backup teruggezet en worden alleen de Companion-bestanden verwijderd die deze run heeft aangemaakt. Een bestand dat al de verwachte inhoud had, blijft staan. Het herstart geen service en wijzigt `/etc/ironkeep.env` niet. De vlag blijft uit.

## Python-importcontrole

Dit opent `/var/lib/ironkeep/ironkeep.db` niet en leest `/etc/ironkeep.env` niet. Het voert `ironkeep.main` niet uit, omdat die import `db.init()` draait en catalogi kan verversen. `main.py` wordt wel gecompileerd.

```bash
cd /opt/ironkeep
/opt/ironkeep/.venv/bin/python /home/ironadmin/companion-phase1-package/check_imports.py
```

Verwacht: `import check ok`, `flag off`, de vijf Companion-paden, en `database (unset)`.

## Herstart en healthcheck

Alleen de website. De bot niet herstarten.

```bash
sudo systemctl restart ironkeep.service
sudo systemctl is-active ironkeep.service
systemctl show ironkeep.service -p ActiveEnterTimestamp
systemctl show ironkeep-bot.service -p ActiveEnterTimestamp
```

De timestamp van `ironkeep-bot.service` moet de oude blijven.

```bash
curl -sS -o /dev/null -w 'login %{http_code}\n' https://ironkeep.gg/login
curl -sS -o /dev/null -w 'privacy %{http_code}\n' https://ironkeep.gg/privacy
curl -sS -o /dev/null -w 'connect %{http_code}\n' 'https://ironkeep.gg/companion/connect'
sudo grep -E '^IRONKEEP_COMPANION_AUTH=' /etc/ironkeep.env || echo 'flag unset'
sudo journalctl -u ironkeep.service -n 40 --no-pager
```

Verwacht: login `303`, privacy `200`, connect `404`, en geen regel `IRONKEEP_COMPANION_AUTH` in de configuratie. De vlag blijft uit tot een aparte, latere stap.

## Rollback

Mislukt de installatie zelf, dan heeft `install.sh` de zes bestanden al teruggezet en de zojuist aangemaakte Companion-bestanden verwijderd. De backup-map blijft staan.

Voor een handmatige rollback daarna: gebruik de file-backup van `--backup-dir`, of het archief `/home/ironadmin/ironkeep-pre-companion-20261105-172517.tar.gz`. De SQLite-backup `/var/lib/ironkeep/ironkeep.db.backup-20261105-172401` blijft onaangeroerd: deze installatie migreert geen bestaande tabellen zolang de vlag uit staat.

```bash
sudo systemctl stop ironkeep.service
sudo cp -a /home/ironadmin/companion-phase1-files-20261105/config.py /opt/ironkeep/ironkeep/config.py
sudo cp -a /home/ironadmin/companion-phase1-files-20261105/discord_api.py /opt/ironkeep/ironkeep/discord_api.py
sudo cp -a /home/ironadmin/companion-phase1-files-20261105/db.py /opt/ironkeep/ironkeep/db.py
sudo cp -a /home/ironadmin/companion-phase1-files-20261105/main.py /opt/ironkeep/ironkeep/main.py
sudo cp -a /home/ironadmin/companion-phase1-files-20261105/templates/settings.html /opt/ironkeep/ironkeep/templates/settings.html
sudo cp -a /home/ironadmin/companion-phase1-files-20261105/static/js/settings.js /opt/ironkeep/ironkeep/static/js/settings.js
sudo rm -f /opt/ironkeep/ironkeep/companion_auth.py /opt/ironkeep/ironkeep/templates/companion_connect.html
sudo systemctl start ironkeep.service
```

Controleer daarna de zes oorspronkelijke hashes uit de tabel hierboven. Herstel de configuratie alleen als er toch een vlagregel is toegevoegd. Herstart `ironkeep-bot.service` niet. Herstel de database niet voor deze rollback.
