# PULSE — Rapido-Inspired 2D SVG Bus Marker Specification (`docs/BUS_SVG_MARKER_IMPLEMENTATION.md`)

## 1. Design Overview
Ordinary circular vehicle dots have been replaced with a bespoke, vector-drawn top-down 2D city bus icon inspired by modern ride-hailing and fleet tracking interfaces (Rapido, Uber).

## 2. Vector Specifications (`createBusSvg`)
- **ViewBox**: `0 0 64 120` (aspect ratio 1:1.875).
- **Display Dimensions**: Width 32px, Height 60px.
- **Anchor Offsets**: `iconAnchor: [16, 30]`, `popupAnchor: [0, -28]`.

### Structural SVG Elements
1. **Four Side Wheels**: Tread rectangles along vehicle flanks (`fill="#1e293b"`):
   - Front-left (`x="2" y="18" w="5" h="18"`)
   - Front-right (`x="57" y="18" w="5" h="18"`)
   - Rear-left (`x="2" y="84" w="5" h="18"`)
   - Rear-right (`x="57" y="84" w="5" h="18"`)
2. **Aerodynamic Bus Body**: Rounded chassis (`rx="10" ry="10" fill="#ffffff"`), stroked with freshness-matched border.
3. **Twin Directional Headlight Beams**: Angled light polygons (`#FEF08A`) projecting forward, indicating vehicle movement direction.
4. **Front Bumper Accent**: Luminous colored strip across vehicle nose.
5. **Destination Display Matrix**: Amber/yellow electronic board (`#FACC15`) above windshield.
6. **Curved Front Windshield**: Tapered geometry with realistic glass gradient (`#E0F2FE` to `#93C5FD`).
7. **Side Mirrors & Passenger Windows**: Aerodynamic external mirrors and dark glass strips along both sides (`#334155`).
8. **Roof AC Climate Unit**: Central ventilation pod with three horizontal louvers.
9. **Rear Glass & Brake Taillights**: Dual crimson brake indicators (`#EF4444`) at the rear bumper.

## 3. Freshness Halos & Heading Rotation
- **Dynamic Rotation**: Vehicle CSS rotation `transform: rotate(${rotation}deg)` driven by GPS bearing transmitted by the AVL feed.
- **Freshness Halos**: Luminous SVG drop-shadow filter (`stdDeviation="3.0"`):
  - **FRESH** (Age $\le$ 60s): `#10B981` (Bright Green)
  - **AGING** (60s < Age $\le$ 90s): `#F59E0B` (Amber)
  - **STALE** (Age > 90s): `#EF4444` (Vibrant Red)
