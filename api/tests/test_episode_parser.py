from __future__ import annotations

import pytest

from app.scanner.episode_parser import parse_episode


@pytest.mark.parametrize(
    ("filename", "parents", "expected"),
    [
        ("Pluribus S01E01.mkv", [], (1, 1, "S01E01")),
        ("Show s1e2.mp4", [], (1, 2, "S01E02")),
        ("Show S01.E02.mkv", [], (1, 2, "S01E02")),
        ("Show 1x15 Title.mp4", [], (1, 15, "S01E15")),
        ("01 - Show 2x01 Title.mp4", [], (2, 1, "S02E01")),
        ("Cowboy Bebop (1998) E04.mkv", [], (None, 4, "E04")),
        ("Cowboy Bebop (1998) E04.mkv", ["Season 02"], (2, 4, "S02E04")),
        ("Crayon Shin-chan S06E214.mp4", [], (6, 214, "S06E214")),
        ("Doraemon S01E0001.avi", [], (1, 1, "S01E0001")),
        ("069.mp4", [], (None, 69, "E069")),
        ("LT_15.mp4", [], (None, 15, "E15")),
        ("015 - Title.mp4", [], (None, 15, "E015")),
        ("16 - Show 2x16 Title.mp4", [], (2, 16, "S02E16")),
        ("05 - El Siguiente Programa 1x05 Title.mp4", ["Temporada 1"], (1, 5, "S01E05")),
        ("01.mp4", ["Season 06"], (6, 1, "S06E01")),
        ("Fishman Island 10.mkv", ["Season 14"], (14, 10, "S14E10")),
        ("Bobobo - 01.mp4", [], (None, 1, "E01")),
        ("foo.mp4", ["El Show, Temporada 3"], (None, None, None)),
        ("Show - 1080p.mkv", [], (None, None, None)),
        ("Show 2025.mkv", [], (None, None, None)),
        ("Show 1920x1080.mkv", [], (None, None, None)),
        ("GitS_SAC 15 [www.animemf.net] Seba_767.mkv", [], (None, None, None)),
    ],
)
def test_parse_episode(filename: str, parents: list[str], expected):
    marker = parse_episode(filename, parents)
    assert (marker.season, marker.episode, marker.label) == expected
