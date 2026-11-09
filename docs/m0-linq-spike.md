# M0: Linq spike

**Question:** can a Linq iMessage line run a group chat with both household phones, and do 🥇 🥈 🥉 🚫 reactions reach the agent as those emoji?

Everything after M0 depends on the answer, so this gate is checked first.

## What to confirm

| Check | How | Status |
|---|---|---|
| API token works | `python3 scripts/m0_spike.py numbers` | Blocked: token rejected (401, "Invalid or expired token"), Nov 9 |
| Group chat on the free shared line | `group` with both phones | Not run |
| Test pick with trailer link renders | look at both phones | Not run |
| Custom emoji reactions arrive as emoji | `poll`, then webhook | Not run |
| Standard tapbacks arrive (fallback) | ❤️ 👍 ‼️ 👎 on the same message | Not run |
| Real monthly price | Linq dashboard or sales | Not checked |

## Known constraints

- The free shared line allows 20 contacts, and each contact has to text the line first. Both phones already have.
- Linq's docs say a group chat needs two or more recipients and iMessage or RCS. Nobody has confirmed that the free shared line allows group chats.
- Webhooks need a public HTTPS URL. A cloud dev session can't receive inbound traffic, so M0 checks reactions by polling the chat first and tests the webhook once the service is hosted.

## Outcomes

- **Pass:** build on Linq.
- **Only standard tapbacks come through:** map ❤️ gold, 👍 silver, ‼️ bronze, 👎 veto, or accept text replies like "1 3 2 veto".
- **No group chats on the free line, or the price is too high:** fall back to BlueBubbles on an always-on Mac.
