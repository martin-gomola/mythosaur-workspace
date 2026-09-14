from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import requests

from ...common import ToolDef, bool_env, err, listify_strings, now_ms, ok, parse_int
from ..google_plugin import READ_TOOL
from . import _auth, _capabilities, _validation


def _maps_post(tool_name: str, url: str, payload: dict[str, Any], field_mask: str, started: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    blocked = _auth._maps_api_guard(tool_name, started)
    if blocked:
        return None, blocked

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _auth._maps_api_key_value(),
        "X-Goog-FieldMask": field_mask,
    }
    if referrer := _auth._maps_referrer_value():
        headers["Referer"] = referrer

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=_capabilities._MAPS_DEFAULT_TIMEOUT_SEC)
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, err(tool_name, "maps_api_failed", _validation._safe_error_msg(exc), "google", started)

    try:
        return response.json(), None
    except ValueError:
        return None, err(tool_name, "maps_api_invalid_response", "invalid JSON in API response", "google", started)


def _maps_normalize_travel_mode(raw: str) -> str:
    value = raw.strip().lower()
    mapping = {
        "drive": "DRIVE",
        "driving": "DRIVE",
        "walk": "WALK",
        "walking": "WALK",
        "bicycle": "BICYCLE",
        "bike": "BICYCLE",
        "transit": "TRANSIT",
        "two_wheeler": "TWO_WHEELER",
        "two-wheeler": "TWO_WHEELER",
        "motorcycle": "TWO_WHEELER",
    }
    return mapping.get(value, raw.strip().upper() or "DRIVE")


def _maps_link_travel_mode(raw: str) -> str:
    value = raw.strip().lower()
    mapping = {
        "drive": "driving",
        "driving": "driving",
        "walk": "walking",
        "walking": "walking",
        "bicycle": "bicycling",
        "bike": "bicycling",
        "transit": "transit",
        "two_wheeler": "driving",
        "two-wheeler": "driving",
        "motorcycle": "driving",
    }
    return mapping.get(value, value or "driving")


def _maps_build_route_link(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_maps_build_route_link", "maps", started)
    if blocked:
        return blocked

    origin = (args.get("origin") or "").strip()
    destination = (args.get("destination") or "").strip()
    if not origin or not destination:
        return err(
            "google_maps_build_route_link",
            "missing_args",
            "origin and destination are required",
            "google",
            started,
        )

    travel_mode = _maps_link_travel_mode(str(args.get("travel_mode") or "driving"))
    waypoints = listify_strings(args.get("waypoints"))
    params = {
        "api": 1,
        "origin": origin,
        "destination": destination,
        "travelmode": travel_mode,
    }
    if waypoints:
        params["waypoints"] = "|".join(waypoints)
    if bool_env("MW_GOOGLE_MAPS_NAVIGATE_DEFAULT", False) or bool(args.get("navigate")):
        params["dir_action"] = "navigate"
    url = "https://www.google.com/maps/dir/?" + urlencode(params)

    return ok(
        "google_maps_build_route_link",
        {
            "origin": origin,
            "destination": destination,
            "travel_mode": travel_mode,
            "waypoints": waypoints,
            "url": url,
        },
        "google",
        started,
    )


def _maps_build_place_link(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_maps_build_place_link", "maps", started)
    if blocked:
        return blocked

    query = (args.get("query") or "").strip()
    place_id = (args.get("place_id") or "").strip()
    if not query and not place_id:
        return err(
            "google_maps_build_place_link",
            "missing_args",
            "query or place_id is required",
            "google",
            started,
        )

    params: dict[str, Any] = {"api": 1}
    if query:
        params["query"] = query
    if place_id:
        params["query_place_id"] = place_id
    url = "https://www.google.com/maps/search/?" + urlencode(params)

    return ok(
        "google_maps_build_place_link",
        {
            "query": query,
            "place_id": place_id,
            "url": url,
        },
        "google",
        started,
    )


def _maps_search_places(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_maps_search_places", "maps", started)
    if blocked:
        return blocked

    query = (args.get("query") or "").strip()
    if not query:
        return err("google_maps_search_places", "missing_args", "query is required", "google", started)

    payload: dict[str, Any] = {
        "textQuery": query,
        "maxResultCount": parse_int(args.get("max_results"), 5, minimum=1, maximum=10),
    }
    if language_code := (args.get("language_code") or "").strip():
        payload["languageCode"] = language_code
    if region_code := (args.get("region_code") or "").strip():
        payload["regionCode"] = region_code
    if included_type := (args.get("included_type") or "").strip():
        payload["includedType"] = included_type
    if "open_now" in args:
        payload["openNow"] = bool(args.get("open_now"))

    response_json, api_error = _maps_post(
        "google_maps_search_places",
        "https://places.googleapis.com/v1/places:searchText",
        payload,
        "places.id,places.displayName,places.formattedAddress,places.googleMapsUri,places.location,places.types,nextPageToken",
        started,
    )
    if api_error:
        return api_error

    places = []
    for place in response_json.get("places") or []:
        location = place.get("location") or {}
        places.append(
            {
                "id": place.get("id", ""),
                "display_name": ((place.get("displayName") or {}).get("text")) or "",
                "formatted_address": place.get("formattedAddress", ""),
                "google_maps_uri": place.get("googleMapsUri", ""),
                "location": {
                    "latitude": location.get("latitude"),
                    "longitude": location.get("longitude"),
                },
                "types": place.get("types") or [],
            }
        )

    return ok(
        "google_maps_search_places",
        {
            "query": query,
            "places": places,
            "next_page_token": response_json.get("nextPageToken", ""),
        },
        "google",
        started,
    )


def _maps_compute_route(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_maps_compute_route", "maps", started)
    if blocked:
        return blocked

    origin = (args.get("origin") or "").strip()
    destination = (args.get("destination") or "").strip()
    if not origin or not destination:
        return err(
            "google_maps_compute_route",
            "missing_args",
            "origin and destination are required",
            "google",
            started,
        )

    travel_mode = _maps_normalize_travel_mode(str(args.get("travel_mode") or "DRIVE"))
    payload: dict[str, Any] = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": travel_mode,
        "computeAlternativeRoutes": bool(args.get("alternatives", False)),
    }
    if departure_time := (args.get("departure_time") or "").strip():
        payload["departureTime"] = departure_time
    if routing_preference := (args.get("routing_preference") or "").strip():
        payload["routingPreference"] = _validation._validate_enum(
            routing_preference.upper(), _validation._VALID_ROUTING_PREFERENCES, "TRAFFIC_AWARE",
        )

    intermediates = []
    for waypoint in listify_strings(args.get("waypoints")):
        intermediates.append({"address": waypoint})
    if intermediates:
        payload["intermediates"] = intermediates

    response_json, api_error = _maps_post(
        "google_maps_compute_route",
        "https://routes.googleapis.com/directions/v2:computeRoutes",
        payload,
        "routes.duration,routes.distanceMeters,routes.description,routes.polyline.encodedPolyline,routes.legs.duration,routes.legs.distanceMeters,routes.legs.steps.navigationInstruction.instructions",
        started,
    )
    if api_error:
        return api_error

    routes = []
    for route in response_json.get("routes") or []:
        legs = []
        for leg in route.get("legs") or []:
            steps = []
            for step in leg.get("steps") or []:
                instructions = ((step.get("navigationInstruction") or {}).get("instructions")) or ""
                if instructions:
                    steps.append(instructions)
            legs.append(
                {
                    "distance_meters": leg.get("distanceMeters"),
                    "duration": leg.get("duration"),
                    "steps": steps,
                }
            )
        routes.append(
            {
                "description": route.get("description", ""),
                "distance_meters": route.get("distanceMeters"),
                "duration": route.get("duration"),
                "polyline": ((route.get("polyline") or {}).get("encodedPolyline")) or "",
                "legs": legs,
            }
        )

    return ok(
        "google_maps_compute_route",
        {
            "origin": origin,
            "destination": destination,
            "travel_mode": travel_mode,
            "waypoints": listify_strings(args.get("waypoints")),
            "routes": routes,
            "route_link": (
                lambda r: (r.get("data") or {}).get("url", "")
            )(_maps_build_route_link({
                "origin": origin,
                "destination": destination,
                "waypoints": listify_strings(args.get("waypoints")),
                "travel_mode": _maps_link_travel_mode(travel_mode),
                "navigate": bool(args.get("navigate")),
            })),
        },
        "google",
        started,
    )


def get_tools() -> list[ToolDef]:
    return [
        READ_TOOL(
            name="google_maps_build_route_link",
            description="Build a Google Maps route link from origin, destination, and optional waypoints.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "origin": {"type": "string", "description": "Starting address or place name."},
                    "destination": {"type": "string", "description": "Destination address or place name."},
                    "waypoints": {"type": "array", "items": {"type": "string"}, "description": "Intermediate stop addresses or place names."},
                    "travel_mode": {"type": "string", "enum": ["driving", "walking", "bicycling", "transit"], "description": "Travel mode: driving, walking, bicycling, or transit. Defaults to driving."},
                    "navigate": {"type": "boolean", "description": "Open in navigation mode when link is clicked."},
                },
                "required": ["origin", "destination"],
            },
            handler=_maps_build_route_link,
        ),
        READ_TOOL(
            name="google_maps_build_place_link",
            description="Build a Google Maps place/search link.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "description": "Place name or address to search for."},
                    "place_id": {"type": "string", "description": "Google Maps place ID for precise linking."},
                },
                "required": [],
            },
            handler=_maps_build_place_link,
        ),
        READ_TOOL(
            name="google_maps_search_places",
            description="Search Google Maps Places by text query using the Google Maps Places API.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "description": "Text search query (e.g. 'coffee shops near Bratislava')."},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5, "description": "Maximum places to return (1-10). Defaults to 5."},
                    "language_code": {"type": "string", "description": "Language for results (e.g. 'en', 'sk')."},
                    "region_code": {"type": "string", "description": "Region bias for results (e.g. 'SK', 'US')."},
                    "included_type": {"type": "string", "description": "Restrict to a place type (e.g. 'restaurant', 'gas_station')."},
                    "open_now": {"type": "boolean", "description": "Only return places currently open."},
                },
                "required": ["query"],
            },
            handler=_maps_search_places,
        ),
        READ_TOOL(
            name="google_maps_compute_route",
            description="Compute routes between origin and destination using the Google Routes API.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "origin": {"type": "string", "description": "Starting address or place name."},
                    "destination": {"type": "string", "description": "Destination address or place name."},
                    "waypoints": {"type": "array", "items": {"type": "string"}, "description": "Intermediate stop addresses."},
                    "travel_mode": {"type": "string", "enum": ["DRIVE", "WALK", "BICYCLE", "TRANSIT", "TWO_WHEELER"], "description": "Travel mode: DRIVE, WALK, BICYCLE, TRANSIT, or TWO_WHEELER. Defaults to DRIVE."},
                    "routing_preference": {"type": "string", "enum": ["TRAFFIC_UNAWARE", "TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"], "description": "Routing preference: TRAFFIC_UNAWARE, TRAFFIC_AWARE, or TRAFFIC_AWARE_OPTIMAL."},
                    "departure_time": {"type": "string", "description": "Departure time in RFC 3339 format for traffic-aware routing."},
                    "alternatives": {"type": "boolean", "description": "Return alternative routes. Defaults to false."},
                    "navigate": {"type": "boolean", "description": "Include a navigation-mode Google Maps link in the response."},
                },
                "required": ["origin", "destination"],
            },
            handler=_maps_compute_route,
        ),
    ]
