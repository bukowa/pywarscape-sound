"""Tests for SoundBank tree projection and modification propagation in builder.py."""

from src.bnk.bank import BkhdChunk, HircChunk, SoundBank
from src.bnk.chunks import DidxChunk, DidxEntry
from src.bnk.models import CAkAction, CAkEvent, CAkSound
from src.engine.diff import BankDiffResult
from src.engine.graph import BankGraphIndex
from src.ui.features.bank_viewer.builder import build_tree_and_details_from_bank


def test_builder_propagation_for_modified_hirc():
    # Tree: Event(10) -> Action(20) -> Sound(30)
    ev = CAkEvent(id=10, actions=[20])
    act = CAkAction.create_play(id=20, target_id=30)
    snd = CAkSound(id=30, source_id=12345, stream_type=2)

    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        hirc=HircChunk(objects=[ev, act, snd]),
    )
    graph = BankGraphIndex.build(bank)

    # Sound 30 is modified
    diff = BankDiffResult(modified_object_ids=frozenset([30]))
    roots, nodes, details = build_tree_and_details_from_bank(bank, graph, diff_result=diff)

    # Node 30 should be marked modified
    node_snd = nodes["hirc:30"]
    assert node_snd.is_modified is True

    # Node 10 and 20 are parent ancestors; they should have has_modified_children = True
    node_act = nodes["hirc:20"]
    assert node_act.has_modified_children is True
    node_ev = nodes["hirc:10"]
    assert node_ev.has_modified_children is True

    # Category "sounds" should have has_modified_children = True
    cat_sounds = nodes["cat:sounds"]
    assert cat_sounds.has_modified_children is True

    # Root groups should have has_modified_children = True
    assert nodes["group:hierarchy"].has_modified_children is True
    assert nodes["group:categories"].has_modified_children is True
    assert nodes["group:chunks"].has_modified_children is False


def test_builder_propagation_for_modified_media():
    didx = DidxChunk(entries=[DidxEntry(file_id=1001, offset=0, size=500)])
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        didx=didx,
    )
    graph = BankGraphIndex.build(bank)

    diff = BankDiffResult(modified_media_ids=frozenset([1001]))
    roots, nodes, details = build_tree_and_details_from_bank(bank, graph, diff_result=diff)

    media_node = nodes["media:1001"]
    assert media_node.is_modified is True

    didx_node = nodes["chunk:DIDX"]
    assert didx_node.has_modified_children is True

    chunks_group = nodes["group:chunks"]
    assert chunks_group.has_modified_children is True
