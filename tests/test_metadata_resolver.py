"""Unit tests for pluggable Layer 2 metadata resolution pipeline."""

from unittest.mock import MagicMock

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.models import CAkAction, CAkEvent, CAkRanSeqCntr, CAkSound
from src.engine.graph import BankGraphIndex
from src.engine.metadata_resolver import (
    CompositeMetadataResolver,
    GameCatalogProvider,
    GraphHierarchyProvider,
    NodeMetadataInfo,
    ResolutionContext,
    SoundDatabaseProvider,
)
from src.models.metadata import ExplosionAudioMetadata, ProjectileAudioMetadata


def _build_test_bank() -> tuple[SoundBank, BankGraphIndex]:
    """Builds a minimal synthetic SoundBank AST with Event -> Container -> Sound."""
    ev = CAkEvent(id=1001, actions=(2001,))
    act = CAkAction(id=2001, id_ext=3001)
    cntr = CAkRanSeqCntr(id=3001, children=(4001, 4002))
    snd1 = CAkSound(id=4001, source_id=50001, stream_type=2)
    snd2 = CAkSound(id=4002, source_id=50002, stream_type=2)

    hirc = HircChunk(objects=[ev, act, cntr, snd1, snd2])
    bkhd = BkhdChunk(bank_id=999, version=112, language_id=0)
    bank = SoundBank(header=bkhd, hirc=hirc)
    graph_index = BankGraphIndex.build(bank)
    return bank, graph_index


def test_sound_database_provider_resolves_event() -> None:
    provider = SoundDatabaseProvider()
    bank, graph_index = _build_test_bank()
    ev = bank.hirc.objects[0]

    mock_db = MagicMock()
    mock_db.resolve_hash.return_value = "Play_unit_charge_roman"

    ctx = ResolutionContext(bank_name="test.bnk", sound_db=mock_db)
    info = provider.resolve_hirc(ev, bank, graph_index, ctx)

    assert info is not None
    assert info.friendly_label == "Play_unit_charge_roman"
    assert info.category == "Event"
    assert ctx.event_names_by_object_id[1001] == "Play_unit_charge_roman"


def test_game_catalog_provider_links_projectiles_to_event() -> None:
    provider = GameCatalogProvider()
    bank, graph_index = _build_test_bank()
    ev = bank.hirc.objects[0]

    mock_catalog = MagicMock()
    proj = ProjectileAudioMetadata(
        key="att_arrow_fire",
        fire_event="Play_missile_fire_arrow",
    )
    mock_catalog.get_projectiles_for_event.return_value = [proj]
    mock_catalog.get_explosions_for_event.return_value = []

    ctx = ResolutionContext(
        bank_name="test.bnk",
        catalog=mock_catalog,
        event_names_by_object_id={1001: "Play_missile_fire_arrow"},
    )
    info = provider.resolve_hirc(ev, bank, graph_index, ctx)

    assert info is not None
    assert info.friendly_label == "Play_missile_fire_arrow"
    assert info.category == "Projectiles"
    assert info.entity_names == ("att_arrow_fire",)
    assert "1 projectile" in str(info.friendly_details)


def test_graph_hierarchy_provider_propagates_event_to_sound() -> None:
    provider = GraphHierarchyProvider()
    bank, graph_index = _build_test_bank()
    snd = bank.hirc.objects[3]  # CAkSound 4001

    ctx = ResolutionContext(
        bank_name="test.bnk",
        event_names_by_object_id={1001: "Play_sword_hit"},
    )
    info = provider.resolve_hirc(snd, bank, graph_index, ctx)

    assert info is not None
    assert "Play_sword_hit" in str(info.friendly_label)
    assert info.category == "Sound"
    assert "Play_sword_hit" in str(info.friendly_details)


def test_graph_hierarchy_provider_propagates_event_to_media() -> None:
    provider = GraphHierarchyProvider()
    bank, graph_index = _build_test_bank()

    ctx = ResolutionContext(
        bank_name="test.bnk",
        media_referencing_sounds={50001: [4001]},
        event_names_by_object_id={1001: "Play_sword_hit"},
    )
    info = provider.resolve_media(50001, bank, graph_index, ctx)

    assert info is not None
    assert "Play_sword_hit" in str(info.friendly_label)
    assert "WEM 50001" in str(info.friendly_label)
    assert info.category == "Embedded WEM"


def test_composite_metadata_resolver_merges_and_caches() -> None:
    bank, graph_index = _build_test_bank()
    ev = bank.hirc.objects[0]

    mock_db = MagicMock()
    mock_db.resolve_hash.return_value = "Play_fire_ballista"

    mock_catalog = MagicMock()
    mock_catalog.get_projectiles_for_event.return_value = [
        ProjectileAudioMetadata(key="att_ballista_bolt", fire_event="Play_fire_ballista")
    ]
    mock_catalog.get_explosions_for_event.return_value = []

    resolver = CompositeMetadataResolver()
    ctx = ResolutionContext(bank_name="test.bnk", sound_db=mock_db, catalog=mock_catalog)

    info = resolver.resolve_hirc_node(ev, bank, graph_index, ctx)

    assert info is not None
    assert info.friendly_label == "Play_fire_ballista"
    assert info.category == "Projectiles"
    assert info.entity_names == ("att_ballista_bolt",)

    # Verify cached on second call
    info_cached = resolver.resolve_hirc_node(ev, bank, graph_index, ctx)
    assert info_cached is info
