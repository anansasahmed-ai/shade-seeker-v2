---
name: agent-skills-operational-guide
description: Core operational guidelines, location disambiguation rules, and travel mode mapping for private vs public buses.
---

# Agent Skills & Operational Guide

## 1. Location Disambiguation
- Never assume ambiguous city names (e.g., "San Jose", "Portland", "Springfield", "Columbus", "Kansas City") when no state, province, or country is specified.
- If an origin or destination lacks regional context, STOP and ask the user a clarifying question before calling `get_shade_recommendation`.

## 2. Travel Mode Distinction (Buses)
- Public transit buses (city buses, municipal transit networks) map to `TRANSIT`.
- Private or intercity bus lines (e.g., Greyhound, FlixBus, private charters) operate on highways and must map to `DRIVE` to match highway routing capabilities.

## 3. Intelligent Transit Scheduling & Fallbacks
- Long-distance transit routes may not have direct departures at exact requested minutes. Gracefully suggest alternative schedules or driving options when exact matches fail.