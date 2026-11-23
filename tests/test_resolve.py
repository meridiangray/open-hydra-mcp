"""Every tool that takes an `entity` names ONE entry through `hydra.entities.resolve`: an H, a bare body, a key, a
record id, or a title only one entry has. A shared title, a part of a title and a near miss are refused (the
candidates listed), never answered with the first or the closest hit. A Suggestions cast writes the record ids of
the two entries picked, so the link lands on the one the person chose."""
import json

import pytest

from hydra import entities, graphquery
from hydra.cli import init as hinit
from hydra.cli import main as cli
from hydra_mcp import agent, article, core, pipeline, suggestions

P = lambda i, s, **p: {"id": i, "schema": s, "properties": {k: v if isinstance(v, list) else [v] for k, v in p.items()}}


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    r = tmp_path_factory.mktemp("res") / "res"
    hinit.create(r, name="res", prefix="res", universe=True)
    recs = [P("t1", "Person", name="Turki bin Abdullah", birthDate="1900"),
            P("t2", "Person", name="Turki bin Abdullah", birthDate="1950"),
            P("ae", "Person", name="Abdul Elah bin Saud"),
            P("w", "PublicBody", name="Ministry of Works"), P("r", "PublicBody", name="Ministry of Roads"),
            P("d1", "Position", name="Deputy Minister", organization="Ministry of Works"),
            P("d2", "Position", name="Deputy Minister", organization="Ministry of Roads"),
            P("ann", "Person", name="Ann Lee", position="Deputy Minister")]
    (r / "collections" / "res.json").write_text(json.dumps(recs), encoding="utf-8")
    assert cli(["build", str(r)]) == 0 and cli(["universe", str(r), "build"]) == 0
    return core.open_archive(str(r))


def _entity_tools(root):
    """Every MCP entry point that takes one `entity`, as a call on a reference."""
    return {
        "explain_entity": lambda e: agent.explain_entity(root, e),
        "records_of": lambda e: agent.records_of(root, e),
        "article_sections": lambda e: article.article_sections(root, e),
        "set_article_section": lambda e: article.set_article_section(root, e, "Life", "Text."),
        "remove_article_section": lambda e: article.remove_article_section(root, e, "Life"),
        "move_article_section": lambda e: article.move_article_section(root, e, "Life", 1),
        "suggestions": lambda e: suggestions.suggestions(root, e),
        "cast": lambda e: suggestions.cast(root, e, "appoint", "Deputy Minister"),
        "probe": lambda e: suggestions.probe(root, e, "wikidata"),
        "apply_suggestion": lambda e: suggestions.apply(root, e, "appoint.x"),
        "dismiss_suggestion": lambda e: suggestions.dismiss(root, e, "appoint.x"),
        "enrichments": lambda e: suggestions.enrichments(root, e),
        "enrichment_hide": lambda e: suggestions.enrichment_hide(root, e, "x"),
        "enrichment_delete": lambda e: suggestions.enrichment_delete(root, e, "x"),
        "suggestions_reset": lambda e: suggestions.suggestions_reset(root, e),
        "wikidata_purge": lambda e: suggestions.wikidata_purge(root, e),
        "read_page": lambda e: pipeline.read_page(root, e),
        "scope": lambda e: _refused(pipeline.scope(root, e)),                 # answers its refusal as {error, why, do}
    }


def _refused(out: dict) -> dict:
    kinds = {"ambiguous entity": "Ambiguous", "no such entity": "NotFound"}
    if out.get("error"):
        raise core.IngestError(out["why"], kind=kinds.get(out["error"], out["error"]))
    return out


def _hs(root, title):
    return sorted(c["h"] for c in entities.catalog(root).search(title) if c["title"] == title)


@pytest.mark.parametrize("ref,kind", [("Turki bin Abdullah", "Ambiguous"),      # a shared title
                                      ("Turki bin", "NotFound"),                # a part of a title
                                      ("Abdul Elah bin Sau", "NotFound")])      # a near miss
def test_resolve_refuses_ambiguous(root, ref, kind):
    both = _hs(root, "Turki bin Abdullah")
    assert len(both) == 2
    for name, call in _entity_tools(root).items():
        with pytest.raises(core.IngestError) as e:
            call(ref)
        assert e.value.kind == kind, (name, str(e.value))
        if kind == "Ambiguous":
            assert all(h in str(e.value) for h in both), name           # the candidates, for the agent to pick
        else:
            assert "Abdul Elah bin Saud (" not in str(e.value).split("near:")[0], name
    out = agent.link_images(root, [{"image": "a.jpg", "kind": "portrait", "entity": ref}])
    assert out["images"] == 0 and out["problems"] and (kind != "Ambiguous" or all(h in out["problems"][0]["error"] for h in both))
    for call in (lambda: graphquery.neighbors(root, ref), lambda: graphquery.tags(root, ref),
                 lambda: graphquery.paths(root, ref, "Ann Lee")):
        with pytest.raises(graphquery.GraphError):
            call()


def test_an_h_and_a_bare_body_resolve(root):
    cat = entities.catalog(root)
    for h in _hs(root, "Turki bin Abdullah"):
        body = h.rsplit("-", 1)[1]
        recs = cat.records_of(body)
        for ref in (h, body, f"H-{body}", recs[0], recs[0].split("/", 1)[1]):
            assert cat.resolve(ref).body == body
            assert agent.explain_entity(root, ref)["records"] == [recs[0].split("/", 1)[1]]
            assert article.article_sections(root, ref)["h_body"] == body
            assert suggestions.enrichments(root, ref)["body"] == body
            assert pipeline.read_page(root, ref)["h"] == h
            assert graphquery.neighbors(root, ref)["entity"]
    assert cat.resolve("Abdul Elah bin Saud", names="unique").how == "title"              # one page has it
    with pytest.raises(entities.Ambiguous):
        cat.resolve("Abdul Elah bin Saud")                                                   # a name is no proof
    with pytest.raises(entities.NotFound):
        cat.resolve("Abdul Elah bin Saud", kind="Organization", names="unique")


def test_a_cast_lands_on_the_picked_namesake(root):
    """Appoint on one of two "Deputy Minister" posts: the Occupancy names that post's record, and the page links to it."""
    s = next(x for x in suggestions.suggestions(root, "res:ann")["suggestions"] if x["rule"] == "appoint")
    cands = s["preview"]["candidates"]
    assert sorted(c["record"] for c in cands) == ["res:d1", "res:d2"]
    n = next(i for i, c in enumerate(cands) if c["record"] == "res:d2")
    done = suggestions.apply(root, "res:ann", s["id"], {"candidate": n}, confirm=True)
    assert done["args"]["records"][0]["properties"] == {"holder": ["res:ann"], "post": ["res:d2"]}
    cat = entities.catalog(root)
    ann = cat.resolve("res:ann").body
    posts = [r["other"] for r in cat.page(ann)["relations"] if r["edge"] == "Occupancy"]
    assert posts == [cat.resolve("res:d2").body]
