import pytest

from dockedup.cli import AppState


def make_container(container_id, name, project):
    return {
        "id": container_id,
        "name": name,
        "project": project,
        "status": "[green]✅ Up[/green]",
        "health": "[grey50]—[/grey50]",
        "cpu": "[green]0.0%[/green]",
        "memory": "[grey50]—[/grey50]",
        "started_at": None,
    }


@pytest.fixture
def grouped_containers():
    return {
        "proj-a": [
            make_container("a1", "proj-a-web", "proj-a"),
            make_container("a2", "proj-a-db", "proj-a"),
        ],
        "proj-b": [make_container("b1", "proj-b-worker", "proj-b")],
        "proj-c": [
            make_container("c1", "proj-c-1", "proj-c"),
            make_container("c2", "proj-c-2", "proj-c"),
            make_container("c3", "proj-c-3", "proj-c"),
        ],
    }


# --- update_containers ---


def test_update_containers_builds_sorted_projects_and_indices(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)

    assert state.project_names == ["proj-a", "proj-b", "proj-c"]
    assert len(state.all_containers) == 6
    assert state.total_container_count == 6


def test_update_containers_sorts_containers_within_project():
    state = AppState()
    grouped = {
        "proj": [
            make_container("z", "z-container", "proj"),
            make_container("a", "a-container", "proj"),
        ]
    }
    state.update_containers(grouped)
    names = [c["name"] for c in state.all_containers]
    assert names == ["a-container", "z-container"]


def test_update_containers_preserves_selection_by_id(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)
    state.move_selection(2)  # select a2 (index 2, third container overall: a-web, a-db is idx1)
    selected_before = state.get_selected_container()

    state.update_containers(grouped_containers)
    selected_after = state.get_selected_container()

    assert selected_after["id"] == selected_before["id"]


def test_update_containers_resets_selection_when_container_removed(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)
    state.move_selection(5)
    selected = state.get_selected_container()
    assert selected["id"] == "c3"

    del grouped_containers["proj-c"]
    state.update_containers(grouped_containers)

    assert state.selected_index == 0


def test_update_containers_empty_input():
    state = AppState()
    state.update_containers({})
    assert state.all_containers == []
    assert state.get_selected_container() is None


# --- move_selection ---


def test_move_selection_clamps_at_top(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)
    state.move_selection(-10)
    assert state.selected_index == 0


def test_move_selection_clamps_at_bottom(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)
    state.move_selection(100)
    assert state.selected_index == len(state.all_containers) - 1


def test_move_selection_noop_when_empty():
    state = AppState()
    state.move_selection(1)
    assert state.selected_index == 0


def test_move_selection_scrolls_viewport_when_below(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)
    state.viewport_height_projects = 1

    # Move to the last container, which lives in the third project.
    state.move_selection(len(state.all_containers) - 1)

    assert state.scroll_offset == 2


# --- scroll_project_view ---


def test_scroll_project_view_selects_first_container_of_new_project(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)

    state.scroll_project_view(1)

    assert state.scroll_offset == 1
    selected = state.get_selected_container()
    assert selected["id"] == "b1"


def test_scroll_project_view_clamps(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)

    state.scroll_project_view(-5)
    assert state.scroll_offset == 0

    state.scroll_project_view(100)
    assert state.scroll_offset == len(state.project_names) - 1


# --- filter ---


def test_filter_narrows_by_container_name(grouped_containers):
    state = AppState()
    state.filter_text = "worker"
    state.update_containers(grouped_containers)

    assert state.project_names == ["proj-b"]
    assert [c["id"] for c in state.all_containers] == ["b1"]


def test_filter_matches_whole_project_by_project_name(grouped_containers):
    state = AppState()
    state.filter_text = "proj-c"
    state.update_containers(grouped_containers)

    assert state.project_names == ["proj-c"]
    assert len(state.all_containers) == 3


def test_filter_is_case_insensitive(grouped_containers):
    state = AppState()
    state.filter_text = "WEB"
    state.update_containers(grouped_containers)

    assert [c["id"] for c in state.all_containers] == ["a1"]


def test_filter_no_match_yields_empty(grouped_containers):
    state = AppState()
    state.filter_text = "nonexistent"
    state.update_containers(grouped_containers)

    assert state.all_containers == []
    assert state.total_container_count == 6


def test_clear_filter_restores_all_containers(grouped_containers):
    state = AppState()
    state.filter_text = "worker"
    state.update_containers(grouped_containers)
    assert len(state.all_containers) == 1

    state.clear_filter()
    state.update_containers(grouped_containers)

    assert len(state.all_containers) == 6
    assert state.filter_typing is False


def test_filter_typing_lifecycle():
    state = AppState()
    state.start_filter_typing()
    assert state.filter_typing is True

    state.append_filter_char("w")
    state.append_filter_char("e")
    assert state.filter_text == "we"

    state.backspace_filter()
    assert state.filter_text == "w"

    state.confirm_filter()
    assert state.filter_typing is False
    assert state.filter_text == "w"


def test_backspace_filter_on_empty_text_is_noop():
    state = AppState()
    state.backspace_filter()
    assert state.filter_text == ""


# --- project mode ---


def test_toggle_project_mode_syncs_to_current_container_project(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)
    state.move_selection(2)  # b1, project index 1

    state.toggle_project_mode()

    assert state.project_mode is True
    assert state.get_selected_project_name() == "proj-b"


def test_toggle_project_mode_off(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)
    state.toggle_project_mode()
    state.toggle_project_mode()
    assert state.project_mode is False


def test_move_project_selection_clamps(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)

    state.move_project_selection(-5)
    assert state.selected_project_index == 0

    state.move_project_selection(100)
    assert state.selected_project_index == len(state.project_names) - 1


def test_get_containers_in_project_returns_matching_containers(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)

    containers = state.get_containers_in_project("proj-c")

    assert {c["id"] for c in containers} == {"c1", "c2", "c3"}


def test_get_containers_in_project_unknown_project_returns_empty(grouped_containers):
    state = AppState()
    state.update_containers(grouped_containers)

    assert state.get_containers_in_project("does-not-exist") == []


def test_get_selected_project_name_none_when_no_projects():
    state = AppState()
    assert state.get_selected_project_name() is None
