import folium
#testing to see if gemini can read this file and display this

def create_route_map(coords: list[tuple[float, float]]) -> folium.Map:
    if not coords:
        raise ValueError("No coordinates provided for mapping.")

    m = folium.Map(location=coords[len(coords) // 2], zoom_start=9, control_scale=True)
    folium.PolyLine(locations=coords, color="#2563eb", weight=5, opacity=0.8, tooltip="Route Path").add_to(m)
    folium.Marker(location=coords[0], popup="Origin", icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)
    folium.Marker(location=coords[-1], popup="Destination", icon=folium.Icon(color="red", icon="stop", prefix="fa")).add_to(m)

    # Zoom to fit the whole route instead of using a fixed zoom level.
    lats = [lat for lat, _ in coords]
    lons = [lon for _, lon in coords]
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    return m
