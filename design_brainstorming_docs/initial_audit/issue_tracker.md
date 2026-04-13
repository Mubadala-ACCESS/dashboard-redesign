# Monday Issues / Direction Notes

## Purpose of this note
This issue tracker captures the main UX, information-design, and architecture problems identified during the initial dashboard audit, and translates them into the design direction for the redesign effort.

---

## 1. User journey and orientation

### Issue
The current dashboard does not immediately explain what the user is looking at, who it is for, or how to use it. A first-time visitor is expected to infer too much from the layout and controls.

### Why this matters
This makes the dashboard harder to use for non-specialists, external viewers, and anyone unfamiliar with the stations, parameters, or workflows.

### Direction
- Add a short purpose section at the top that answers: **“What am I looking at?”**
- Explain that the page shows **real-time environmental data from monitoring stations across Abu Dhabi**.
- Add a **“How to use this dashboard”** tooltip, help panel, or onboarding overlay.
- Include simple orientation guidance:
  - what the parameters mean
  - what stations are included
  - how to move between quick exploration and deeper analysis

---

## 2. User pathways are not clearly separated

### Issue
The current dashboard tries to serve both general users and scientific users at once, without making those pathways explicit.

### Why this matters
This increases cognitive load. Non-specialists may feel overwhelmed, while scientific users may still have to work too hard to reach detailed analysis tools.

### Direction
Create two clear usage pathways:

#### Quick view
For the general public or non-specialists:
- high-level information first
- simple summaries
- readable ranges
- minimal clutter

#### Advanced analysis
For researchers:
- deeper graph exploration
- access to downloadable graphs or tables
- more detailed filtering and drill-down controls

### Design implication
The **general-public pathway should be the default**, while advanced scientific controls should be accessible but not dominate the first screen.

---

## 3. The dashboard shows data, but does not interpret it enough

### Issue
The current interface exposes values and graphs, but often leaves users to decide for themselves whether a reading is normal, moderate, or concerning.

### Why this matters
Data without interpretive context is much less useful for non-specialists and slows down comprehension even for experienced users.

### Direction
- Add **normal-range bands** on graphs where appropriate.
- Add **color-coded thresholds or benchmarks** for key parameters such as PM2.5.
- Add short **“What this means”** interpretations alongside important values.
- Where appropriate, add plain-language guidance such as:
  - “Unhealthy for sensitive groups”
  - “Limit exposure”

### Example
- PM2.5 = 42 should not appear as just a number.
- It should include context such as:
  - **Status:** Unhealthy for sensitive groups
  - **Interpretation:** Air quality is degraded
  - **Recommendation:** Limit prolonged outdoor exposure

---

## 4. Scientific terminology needs support

### Issue
Terms such as PM2.5, PM10, and related environmental variables may not be self-explanatory to all users.

### Why this matters
Without guidance, users may see the data without understanding why it matters.

### Direction
- Add a linked **glossary** or expandable term definitions.
- Include concise explanations for:
  - PM2.5
  - PM10
  - atmospheric pressure
  - other high-frequency dashboard terms
- Explain why each metric matters in practical terms.

---

## 5. Important environmental context is missing

### Issue
The dashboard does not currently do enough to help explain why patterns in the data may have changed.

### Why this matters
Environmental data can be misleading without event context.

### Direction
Add event markers or overlays where useful for:
- dust storms
- rain events
- heatwaves

This will help users connect changes in graphs to real environmental events.

---

## 6. The dashboard is too visually flat

### Issue
The current dashboard is functional but feels visually flatter than desired.

### Why this matters
A flatter visual hierarchy makes the interface feel more utilitarian and makes it harder to scan quickly.

### Direction
- Strengthen the visual hierarchy.
- Make summaries more prominent.
- Improve contrast between:
  - overview information
  - filters
  - controls
  - graph areas
  - metadata
- Use spacing, typography, grouping, and calmer card hierarchy to make the layout feel more polished and professional.

---

## 7. Search and filters need stronger hierarchy

### Issue
Search and filters are present, but they do not stand out strongly enough as the main way to explore the dashboard.

### Why this matters
Users should be able to understand the exploration controls at a glance.

### Direction
- Give search and filters stronger hierarchy.
- Make them easier to scan quickly.
- Improve filter grouping and labeling.
- Reduce the feeling that all controls have the same visual weight.

---

## 8. Station summary should come before dense scientific controls

### Issue
The current layout exposes technical or scientific detail too early in the reading order.

### Why this matters
Users need a quick station-level understanding before facing detailed graphs or analysis controls.

### Direction
Reorder the page so the station summary appears first:
- station name
- status
- location
- latest reading
- quick summary
- main actions

Then place denser scientific controls and detailed graph interactions below or inside drill-down sections.

---

## 9. Live-data page readability needs improvement

### Issue
The live-data page is not calm enough visually and can feel too card-heavy or cluttered.

### Why this matters
Live data should be easy to scan quickly. The current layout makes rapid interpretation harder than it should be.

### Direction
- Improve readability of the live-data page.
- Reduce card clutter.
- Improve grouping and labeling.
- Make units, ranges, and latest values easier to interpret quickly.
- Create a calmer, more structured reading experience.

---

## 10. The architecture is too tightly coupled

### Issue
The current dashboard architecture mixes page rendering and direct data access too tightly.

### Why this matters
This makes the system harder to maintain, harder to scale, and harder to evolve cleanly.

### Direction
- Refactor the dashboard architecture so page rendering is less tightly coupled with direct data access.
- Move toward a cleaner separation between:
  - frontend presentation
  - backend services
  - database access
- Support the migration away from the current Dash + direct MongoDB structure toward:
  - FastAPI backend
  - PostgreSQL/PostGIS data layer
  - cleaner HTML/CSS/JavaScript frontend

---

## 11. Clutter needs to be reduced

### Issue
The current dashboard exposes too much at once, making it harder for users to identify the most important information quickly.

### Why this matters
Dense layouts reduce clarity and make onboarding harder.

### Direction
- Make the general-public pathway the default.
- Show a simpler summary view first.
- Keep filters such as station, parameter, and time range available.
- Put more detailed graph exploration behind drill-down interactions.
- Collapse less-used metrics behind tabs.
- Group related metrics together, such as:
  - air quality
  - weather

---

## 12. Mobile support needs improvement

### Issue
The dashboard needs better mobile responsiveness.

### Why this matters
A monitoring dashboard should remain usable across screen sizes, especially for quick checks and field-friendly access.

### Direction
- Improve mobile support across the full layout.
- Ensure the map resizes automatically.
- Make map interactions touch-friendly.
- Improve responsive behavior for filters, cards, and page sections.

---

## 13. Priority summary for redesign

### Highest-priority issues
1. Current dashboard is functional but visually flatter than desired.
2. Search and filters need stronger hierarchy.
3. Station summary should appear before dense scientific controls.
4. Live-data page needs clearer readability and less card clutter.
5. Current architecture mixes page rendering and direct data access too tightly.

---

## 14. Immediate redesign direction

### Frontend direction
- Introduce a clearer purpose section.
- Create a Quick View and Advanced Analysis pathway.
- Strengthen hierarchy in search, filters, and summaries.
- Reorder pages around summary-first flow.
- Improve interpretability with thresholds, glossary support, and event context.
- Reduce clutter and improve mobile responsiveness.

### Backend direction
- Decouple UI rendering from direct data access.
- Move toward a FastAPI-driven service layer.
- Replace MongoDB-heavy page logic with cleaner backend access patterns.
- Support longer-term migration to PostgreSQL/PostGIS.

---

## 15. Outcome expected from this redesign phase
The redesigned dashboard should feel:
- more intuitive for laymen
- still useful for scientists
- visually stronger
- calmer and easier to scan
- easier to maintain architecturally
- better prepared for long-term evolution beyond the current Dash structure