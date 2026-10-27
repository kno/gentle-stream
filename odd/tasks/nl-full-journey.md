# PM-011: NL full-journey orchestration

One prompt → complete journey with natural-language stage descriptions, curves, genres.

**Specs:**
- `journey create "build from calm ambient through energetic synthwave then wind down"` generates multi-stage journey
- Gentle Shell produces `{"stages": [{"name": "...", "seconds": N, "to": {...}, "curve": "...", "genre": "..."}]}`
- Save and play immediately

**Next turno:** Extend Gentle Shell prompt to generate full journeys (not just one stage).

## Log

- L1: PM-011 task created; pending Gentle Shell enhancement
