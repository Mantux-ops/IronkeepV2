# WoW Forever API research for Ironkeep

Live Herberg JSON was not retrieved. This environment has no Battle.net application credentials. The available secret names are `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, and `IRONKEEP_SSH_KEY`. None of those is a Blizzard client id or client secret, and the production host was not opened to look for one.

The read-only script is `fetch_herberg.py`. Run it only after the two Battle.net variables below are set. It does not import Ironkeep, write to the database, or change Discord OAuth. Pull request 36 was not modified.

## What has to be set before a live read

Create a client at <https://develop.battle.net/access/clients>. The Battle.net account needs an authenticator, and the developer terms have to be accepted. The client-credentials grant does not need a redirect URI.

```bash
export BLIZZARD_CLIENT_ID="the client id"
export BLIZZARD_CLIENT_SECRET="the client secret"
python3 research/wow_forever/fetch_herberg.py
```

`BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET` are Battle.net application credentials. `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET` are a different OAuth application and will not authenticate this API.

Optional overrides are `BLIZZARD_REGION` (`eu`), `BLIZZARD_GUILD_SLUG` (`herberg`), and `BLIZZARD_LOCALE` (`en_GB`). Sanitized JSON is written to `research/wow_forever/samples/live/`, which is gitignored. The roster file keeps the first three members and records the total. Check the variables without calling Battle.net:

```bash
python3 research/wow_forever/fetch_herberg.py --check-config
```

## Authentication

| Question | Finding | Confidence |
| --- | --- | --- |
| Are client credentials required? | Yes. An application access token from `POST https://oauth.battle.net/token` with `grant_type=client_credentials`. | Confirmed for the Battle.net host. A valid token reading Herberg was not repeated here. |
| Can the guild roster be read with that application token? | Community probes on 5 November 2026 say yes for `profile-forever-{region}`. Official retail docs put guild and character profile outside the user-token-only list. | Reported, not re-tested against Herberg. |
| Is a player's own Battle.net login required? | Not for the guild, roster, or a public character profile. It is required for `GET /profile/user/wow`, protected character, and account collections. Those use the authorization-code flow and the `wow.profile` scope. | Official docs, plus a community check that the account profile lists characters below level 10. |
| What limits apply? | 36,000 requests an hour and 100 requests a second, per client. Crossing the hourly quota slows the client. Crossing the per-second limit returns 429 for the rest of that second. One credential pair per application. Credentials are not shared with players or with the Companion. Access tokens last 24 hours. | Official getting-started and OAuth text. |

A request that omits `Authorization` is a trap. On 6 November 2026 at about 00:35 Europe/Amsterdam, `GET` of the Herberg guild URL, the roster URL, and the Forever ruleset index, all without a header, returned HTTP 404 with an empty body and `server: blizzard`. The same guild URL with `Authorization: Bearer invalid-token` returned HTTP 401, also empty. A retail profile URL behaved the same way. A missing token therefore looks like "not found". The script only treats 404 as a missing document after it has sent a token.

`POST https://oauth.battle.net/token` without a client id and secret returned HTTP 401 and this body:

```json
{"error":"unauthorized","error_description":"An Authentication object was not found in the SecurityContext"}
```

The saved probe list is `samples/unauthenticated-probe.json`.

## Herberg, from the public armory only

<https://worldofwarcraft.blizzard.com/en-us/forever/eu/armory/guild/herberg> rendered, in the same check, as guild Herberg, 140 members, ruleset Normal, founded 2026. That page did not expose the guild id or the roster JSON. The API slug is expected to be `herberg` because the armory path uses that word. The API document itself is unconfirmed until a real token is used.

## Endpoints

Forever is not in Blizzard's published API reference. Retail paths still show a realm slug. Both community reports say Forever has no realm in the path: characters and guilds are addressed by name, and rulesets replace realms. Region hosts stay `eu.api.blizzard.com`, `us.api.blizzard.com`, `kr.api.blizzard.com`, and `tw.api.blizzard.com`.

Namespaces reported by both sources:

- `dynamic-forever-eu`
- `profile-forever-eu`
- `static-forever-eu` (an alias; the `battlenet-namespace` response header names the pinned build, reported as `static-1.60.1_70399-forever`)

| Namespace | Path | Reported result | This research |
| --- | --- | --- | --- |
| `profile-forever-eu` | `/data/wow/guild/{guild-slug}` | 200. Guild profile, `ruleset` instead of `realm`. | Gateway returns 401 for a bad token and 404 with no token. Document not read. |
| `profile-forever-eu` | `/data/wow/guild/{guild-slug}/roster` | 200. Every member, including below level 10. | Same gateway behavior. Document not read. |
| `profile-forever-eu` | `/data/wow/guild/{guild-slug}/activity` | 200 with an empty activity list, as of the morning of 5 November 2026. | Not called with a valid token. |
| `profile-forever-eu` | `/data/wow/guild/{guild-slug}/achievements` | 200 and empty so far. | Not called with a valid token. |
| `profile-forever-eu` | `/profile/wow/character/{first}-{surname}` | 200 from level 10, after logout. 404 below 10. | Not called. |
| `profile-forever-eu` | `.../equipment`, `.../professions`, and the other usual character subpaths | 200 from level 10. `hunter-pets` and `soulbinds` are 404. | Not called. |
| `profile-forever-eu` | `/profile/user/wow` | 200 with a user token and scope `wow.profile`. Lists that account's characters, including below level 10. | Not called. Individual authorization is required. |
| `profile-forever-eu` | `/data/wow/search/character` and `/data/wow/search/guild` | 404. No name search. | Not called. |
| `dynamic-forever-eu` | `/data/wow/ruleset/index` and `/data/wow/ruleset/{id}` | 200. EU ids 1 PvP, 2 Normal, 3 Roleplay, 15 Roleplay PvP. | Bad token returns 401. Index not read. |
| `dynamic-forever-eu` | `/data/wow/realm/index` | 404 since the launch-day republish. | Not called. |
| `static-forever-eu` | playable class, race, item, profession, and the other game-data indexes | 200. 9 classes. 10 races, including ids 95 and 96. | Not called. |
| `dynamic-forever-eu` | auction routes | The two reports disagree. See below. | Not used for this recommendation. |

Auction conflict, so it is unconfirmed: the morning notes of 5 November 2026 (09:15 UTC, 10:15 Europe/Amsterdam) say ruleset auction indexes and listings return data. The forum post later that day says `/data/wow/ruleset/{id}/auctions` is 404. Those can be different paths (`/auctions/index` versus `/auctions` and a trailing slash). Ironkeep does not need auctions.

A namespace the gateway does not know is reported as 403. A known namespace with nothing at that path is reported as 404. Versioned static namespaces other than `static-1.60.1_70399-forever` were reported as 403.

## Fields

Confirmed here means a community response printed the field. It does not mean Herberg was fetched. `samples/field-list.example.json` repeats the same list and is labeled as not a live response.

Guild, profile namespace:

- Confirmed: `id`, `name`, `faction.type`, `faction.name`, `achievement_points`, `member_count`, `created_timestamp`, `slug`, `ruleset.name`, `ruleset.id`, `name_search`, and hrefs for `roster`, `achievements`, and `activity`.
- Not present: `realm`. Rank names are not on the guild document.

Roster member:

- Confirmed: `character.name`, `character.surname`, `character.slug`, `character.id`, `character.level`, `character.playable_class.id`, `character.playable_race.id`, `character.faction.type`, `character.key.href`, and `rank`.
- `rank` 0 is the guild master. The rank title is not in the payload.
- Class and race on the roster are numeric ids. Names are not on the roster object. Names are on the level-10 character profile (`character_class.name`, `race.name`) and in the static indexes.

Character profile, level 10 and above, after logout:

- Confirmed: `id`, `name`, `surname`, `name_search`, `faction`, `race` (`id`, `name`), `character_class` (`id`, `name`), `level`, `experience`, `guild` (`name`, `id`, `slug`), `ruleset`, `last_login_timestamp`, `average_item_level`, and an `equipment` href.
- The published sample was abbreviated with `...`, so more fields exist and were not listed. Do not invent them.
- Explicitly absent: `realm`, `active_spec`, `active_title`.
- `last_login_timestamp`, and the `last-modified` header, move when the character logs out. They do not update while the character is online.
- Below level 10 the profile URL is 404. The roster still includes those characters.

Equipment and professions:

- Confirmed only at document level: both URLs returned data for level 10+ characters.
- Professions were described as primary and secondary groups, current skill and the cap for that rank (75, 150, and so on), and known recipes. Cooking, Fishing, and First Aid were named as secondaries.
- Individual equipment item fields were not printed. The retail `equipped_items` shape is an assumption until `samples/live/` contains a real response.

Guild activity and guild achievements answered, and were empty, on the morning of 5 November 2026. Treat "empty" as a snapshot, not as proof the routes will stay empty.

## Ironkeep today

`main` is the Discord trial dashboard. It has no WoW addon and no Companion. The Forever addon and Companion are on `origin/cursor/forever-addon-f675` at `adbb07de485fb0822a4a8dfaf4616a05abfd4b46`. That branch was read for this comparison and was not changed. Pull request 36, on `cursor/wpf-startup-crash-f675`, adds Discord login for the Companion. It does not call Blizzard.

The addon (`addon/Ironkeep/Group.lua`, saved variable `IronkeepDB`) records the officer's current party or raid:

- place and instance type
- each person's joined name from `UnitFullName` (`"First Surname"`), class file, localized class, role, subgroup, and unit GUID
- first seen, last seen, and whether they are still in the group
- a new session after the group has been empty for 20 minutes

It does not read the guild roster, rank, level, race, equipment, or professions. The Companion turns that saved variable into the text report `Ironkeep group` and posts it to `/api/{slug}/attendance`. The website stores at most 40 people, with name, class, role, time seen, and here/left.

## What should come from where

Use Blizzard for the guild directory:

- guild id, name, slug, faction, ruleset, member count, and created time
- the full roster, including offline characters and characters below level 10
- first name, surname, slug, and numeric character id
- level, class id, race id, faction, and numeric rank
- class and race display names from `static-forever-eu`, cached until the `battlenet-namespace` header changes

Keep the addon and Companion for time spent in a group:

- who was actually in the raid or party, role, subgroup, and how long they were there
- presence while people are online, which the profile API does not update until logout
- the copy-out report and the attendance page

Leave these out of the first Blizzard sync:

- equipment and professions, until a live sample confirms the fields
- guild activity and achievements, while those documents are empty
- per-player Battle.net login; the guild roster does not need `wow.profile`
- rank titles; store the number, and let officers name the ranks
- any write to Discord roles, trials, or attendance from the API

## How often to sync

Herberg's public page showed 140 members. A guild document plus a roster is two requests.

| Data | Interval | Why |
| --- | --- | --- |
| Guild and roster | Every 6 hours, plus a manual refresh | Membership changes are infrequent, and the roster itself lags a logout. Two calls per run is about 8 a day. |
| Static class and race names | When `battlenet-namespace` changes | The catalog is versioned with the static build. |
| Activity and achievements | Not on the roster timer | They were empty. A weekly check is enough to notice if Blizzard starts filling them. |
| Profile, equipment, professions | Not in the first sync | 140 characters times several documents becomes hundreds of calls, and the profile updates on logout. Add this later, only for level 10+, and only when the roster level or `last-modified` changed. |

Stay at one request at a time. The 100-per-second cap matters only if a later job fans out. The 36,000-per-hour cap is per Battle.net client, so the secret stays on the server. The Companion should not embed it.

## When the API is missing or stale

Keep the last good roster. Record when it was fetched. An outage must not look like everyone left the guild.

- 401 or 403: keep the last roster and alert. This is a bad or rotated secret, or a namespace Blizzard removed. Do not delete members.
- 404 on the guild, after a token was sent: keep the last roster. Count consecutive failures. Mark the guild unavailable only after repeated 404s, because a missing `Authorization` header also looks like 404.
- 429: keep the last roster. Honor `Retry-After` on a real sync. This proof of concept waits at most two seconds and tries once.
- Network failure: keep the last roster and show the previous fetch time.
- 404 on one character profile: leave the roster row. Below level 10, or not logged out since creation, is a normal 404.
- A roster level can stay behind the profile for a while after level 10. Prefer the profile level when both exist, and keep the roster as the membership source.

Show officers the fetch time next to any Blizzard field so a stale snapshot is visible.

## Matching a Forever character

The API identity is region plus first name plus surname. The same slug on US and EU can be two people. Herberg is EU, ruleset Normal (id 2).

The addon stores one string, `"First Surname"`, from `UnitFullName`. The API stores `name`, `surname`, and `slug` (`{name}-{surname}` in lowercase). Match them like this:

1. Require exactly one space in the addon name. The first token is the first name and the second token is the surname. Compare both, case-insensitively, to `character.name` and `character.surname`.
2. No space, or more than one space: do not guess. Queue it for an officer. Several guildmates can share a first name.
3. Attach `character.id` after that match. Later attendance prefers the id, then the name pair. The addon unit GUID (`Player-...`) is a different identifier and must not be compared to `character.id`.
4. Require the same region. Prefer a roster row whose guild slug is `herberg`. A profile whose guild slug differs is not a Herberg member even when the name matches.
5. There is no character search endpoint. Outside the roster, the only lookup is the exact profile URL, and it 404s under level 10.

Discord nicknames are a weak key for a two-part Forever name. The Albion-style nickname match on `main` should not be reused as the automatic link. An optional later step is letting a member authorize `wow.profile`, which lists every character on that Battle.net account, including alts under level 10. That is separate from the guild application token.

## Sources

- vman-2993, "WoW: Forever API: what works so far, plus a TS client", US Blizzard forums, 5 November 2026, 4:38pm as displayed (the page did not name a timezone): <https://us.forums.blizzard.com/en/blizzard/t/wow-forever-api-what-works-so-far-plus-a-ts-client/60334>
- "WoW: Forever API notes", last checked 5 November 2026, 09:15 UTC (10:15 Europe/Amsterdam): <https://mhuijskens.com/WoWForever/Api/>
- Battle.net getting started (client creation, client-credentials example, 36,000 requests an hour, 100 a second): <https://develop.battle.net/documentation/guides/getting-started>
- Battle.net OAuth scopes and the user-token endpoint list (`/profile/user/wow` and protected character, not the guild roster): <https://develop.battle.net/documentation/guides/using-oauth>
- Public armory page fetched 6 November 2026, about 00:34 Europe/Amsterdam: <https://worldofwarcraft.blizzard.com/en-us/forever/eu/armory/guild/herberg>
- Unauthenticated and invalid-token probes from this environment, 6 November 2026, about 00:35 Europe/Amsterdam, saved in `samples/unauthenticated-probe.json`
- Ironkeep addon and Companion at `adbb07de485fb0822a4a8dfaf4616a05abfd4b46` on `cursor/forever-addon-f675`
