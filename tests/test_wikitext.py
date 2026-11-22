"""Wikitext regexes: template reduction, links, sections, categories, plain text, infobox fields, name keys."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiki.infobox import breed_attributes, fci_number, infobox_fields, measure_range, registries  # noqa: E402
from wiki.names import akc_keys, name_key, wiki_name_keys, wiki_title_keys  # noqa: E402
from wiki.page import classify, parse_page  # noqa: E402
from wiki.wikitext import (categories, link_targets, normalise_title, protect_links, reduce_templates,  # noqa: E402
                           sections, strip_markup_noise, to_text)

# trimmed from the Golden Retriever article (enwiki-20261001)
GOLDEN = """{{Short description|Dog breed}}
{{Infobox dog breed
| name           = Golden Retriever
| altname        = {{ubl|Flat-coated Retriever, Golden|Yellow or Golden Retriever}}
| stock          = {{ubl|[[Flat-coated Retriever]]|[[Tweed Water Spaniel]]}}
| country        = [[Great Britain]]
| maleheight     = {{cvt|22|–|24|in|cm|disp=flip}}
| femaleheight   = {{cvt|20|–|22|in|cm|disp=flip}}
| weight         = {{cvt|55|–|75|lb|kg|disp=flip}}
| coat           = Flat or wavy double coat<!-- per KC -->
| colour         = Any shade of gold or cream
| litter_size    = {{val|7.2|2.7}}{{r|fvs|p=4}}
| kc_name        = [[The Kennel Club]]
| kc_std         = https://www.thekennelclub.org.uk/breed-standards/gundog/retriever-golden/
| fcistd         = http://www.fci.be/Nomenclature/Standards/111g08-en.pdf
}}
The '''Golden Retriever''' is a British [[Dog breed|breed]] of [[retriever]] dog.<ref>{{cite web|url=x|title=y}}</ref>

==History==
[[File:Nous.jpg|thumb|Nous at [[Guisachan]], 1870s]]
Bred by [[Dudley Marjoribanks, 1st Baron Tweedmouth|Sir Dudley Marjoribanks]].
==Description==
===Appearance===
A {{convert|55|-|75|lb|kg}} dog.
===Temperament===
Gentle and affectionate.
== Health ==
A median [[life expectancy]] of 13.2 (13.1–13.2) years. Prone to [[Hip dysplasia (canine)|hip dysplasia]] and
[[haemangiosarcoma]].
=== Cancer ===
[[Lymphoma in animals|Lymphoma]] is common.
== References ==
{{reflist}}
[[Category:Dog breeds originating in Scotland]]
[[Category:FCI breeds|Golden]]
"""


def test_reduce_templates_renders_value_templates_innermost_first():
    text, kept = reduce_templates(protect_links("{{nowrap|{{convert|36|-|44|kg|lb|abbr=on}}}} {{cite web|url=u}}"))
    assert text == "36–44 kg " and kept == []


def test_reduce_templates_keeps_infobox_body_with_children_rendered():
    _, kept = reduce_templates(protect_links(GOLDEN), keep=lambda n: n.startswith("infobox"))
    assert len(kept) == 1 and kept[0].startswith("Infobox dog breed")
    assert "22–24 in" in kept[0] and "{{" not in kept[0]


def test_list_lang_and_constant_templates():
    assert to_text("{{ubl|a|b}}") == "a\nb"
    assert to_text("also {{langr|de|Dackel}} or {{lang-sk|Slovenský čuvač}}") == "also Dackel or Slovenský čuvač"
    assert to_text("1{{ndash}}2 {{circa|1900}}") == "1–2 c. 1900"


def test_links_render_to_labels_and_file_links_vanish_with_nested_captions():
    assert to_text("[[File:x.jpg|thumb|At [[Guisachan]]]] a [[Dog breed|breed]] of [[retriever]]") == "a breed of retriever"


def test_refs_comments_tables_and_bold_are_removed():
    wt = "'''Pug'''<ref name=a/> is<!-- hidden --> small.<ref>{{cite|x}}</ref>\n{| class=wikitable\n| a || b\n|}\nEnd."
    assert to_text(wt) == "Pug is small.\nEnd."


def test_categories_strip_sort_keys_and_skip_comments():
    assert categories(GOLDEN + "<!-- [[Category:Cats]] -->") == ["Dog breeds originating in Scotland", "FCI breeds"]


def test_link_targets_normalise_titles_and_skip_namespaces():
    assert link_targets("[[hip dysplasia (canine)|hips]] [[File:a.jpg]] [[wikt:x|y]] [[Cherry_eye#Signs]]") == [
        "Hip dysplasia (canine)", "Cherry eye"]
    assert normalise_title("lymphoma_in animals#x") == "Lymphoma in animals"


def test_sections_split_on_any_heading_level_and_keep_the_lead():
    secs = sections(GOLDEN)
    assert secs[0][0] == 0 and "Golden Retriever" in secs[0][2]
    assert [(lvl, h) for lvl, h, _ in secs[1:]] == [(2, "History"), (2, "Description"), (3, "Appearance"),
                                                   (3, "Temperament"), (2, "Health"), (3, "Cancer"), (2, "References")]


def test_infobox_fields_keep_piped_links_together():
    body = protect_links("Infobox dog breed\n| country = [[United Kingdom|UK]]\n| name = A")
    assert infobox_fields(body) == {"country": "\x02United Kingdom\x01UK\x03", "name": "A"}


def test_breed_attributes_of_golden_retriever():
    _, kept = reduce_templates(protect_links(strip_markup_noise(GOLDEN)), keep=lambda n: n.startswith("infobox"))
    a = breed_attributes(kept[0])
    assert a["names"] == ["Golden Retriever"]
    assert a["altnames"] == ["Flat-coated Retriever", "Golden", "Yellow", "Golden Retriever"]
    assert a["country"] == ["Great Britain"]
    assert (a["height_min_cm"], a["height_max_cm"]) == (50.8, 61.0)
    assert (a["weight_min_kg"], a["weight_max_kg"]) == (24.9, 34.0)
    assert (a["litter_min"], a["litter_max"]) == (7.2, 7.2)
    assert a["coat"] == "Flat or wavy double coat"
    assert (a["fci_number"], a["fci_group"]) == (111, 8)
    assert a["registries"] == ["The Kennel Club", "FCI"]


@pytest.mark.parametrize("values,dim,expected", [
    (["{{convert|62|-|70|cm|in}}", "59–65 cm"], "cm", (59.0, 70.0)),
    (["61–69 cm (24–27 in)"], "cm", (61.0, 69.0)),
    (["22 to 25 lb"], "kg", (10.0, 11.3)),
    (["Males: 30 kg; females: 25 kg"], "kg", (25.0, 30.0)),
    (["tall"], "cm", (None, None)),
])
def test_measure_range_prefers_metric_and_converts_imperial(values, dim, expected):
    vals = [reduce_templates(protect_links(v))[0] for v in values]
    assert measure_range(vals, dim) == expected


@pytest.mark.parametrize("url,expected", [
    ("http://www.fci.be/Nomenclature/Standards/043g05-en.pdf", (43, 5)),
    ("http://www.fci.be/uploaded_files/142gb1996_en.doc", (142, None)),
    ("http://www.fci.be/en/nomenclature/SALUKI-269.html", (269, None)),
    ("", (None, None)),
])
def test_fci_number_from_standard_url(url, expected):
    assert fci_number({"fcistd": url}) == expected


def test_fci_number_fields_win_over_the_url():
    assert fci_number({"fcinum": "53", "fcigroup": "1", "fcistd": "x/Standards/999g09-en.pdf"}) == (53, 1)


def test_registries_need_a_standard_link():
    assert registries({"akcstd": "http://akc.org/x", "ukcstd": "", "kc_name": "The Kennel Club", "kc_std": "u"}) == [
        "AKC", "The Kennel Club"]


def test_parse_page_breed_record():
    kind, rec = parse_page(1, "Golden Retriever", GOLDEN.replace("<", "&lt;").replace(">", "&gt;"))
    assert kind == "breed"
    assert rec["url"] == "https://en.wikipedia.org/wiki/Golden_Retriever"
    assert rec["lead"] == "The Golden Retriever is a British breed of retriever dog."
    assert rec["origin_countries"] == ["Scotland"]
    assert rec["temperament"] == "Gentle and affectionate."
    assert rec["section_headings"]["health"] == ["Health", "Cancer"]
    assert rec["health_links"] == ["Life expectancy", "Hip dysplasia (canine)", "Haemangiosarcoma", "Lymphoma in animals"]
    assert rec["life_expectancy_study"] == 13.2
    assert "Gentle" not in rec["appearance"] and "55–75 lb" in rec["appearance"]
    assert rec["history"] == "Bred by Sir Dudley Marjoribanks."


def test_classify_breed_disease_other():
    assert classify("Pug", ["infobox dog breed"], []) == "breed"
    assert classify("Slovak Cuvac", ["infobox dogbreed"], []) == "breed"
    assert classify("Dog breed", [], ["Dog breeds"]) == "other"
    assert classify("Nihon Ken Hozonkai", [], ["Dog breeds originating in Japan"]) == "other"
    assert classify("Cherry eye", [], ["Dog diseases", "Eye diseases"]) == "disease"
    assert classify("Luxating patella", [], ["Dog musculoskeletal disorders"]) == "disease"
    assert classify("Osteosarcoma", [], ["Cancer in dogs"]) == "disease"
    assert classify("List of dog breeds", ["infobox dog breed"], ["Dog breeds"]) == "other"
    assert classify("Laika", [], ["Individual dogs in space"]) == "other"


def test_name_key_strips_accents_case_and_punctuation():
    assert name_key("Slovenský čuvač") == "slovensky cuvac"
    assert name_key("St. Bernard") == "st bernard"
    assert name_key("Black & Tan Coonhound") == "black and tan coonhound"


def test_akc_keys_variants_and_nicknames():
    assert akc_keys("Poodle (Toy)", ["Toy"]) == [("poodle toy", "name"), ("poodle", "variant"), ("poodletoy", "variant")]
    assert akc_keys("German Shepherd Dog", ["GSD", "Alsatian (U.K.)"]) == [
        ("german shepherd dog", "name"), ("german shepherd", "variant"), ("germanshepherddog", "variant"),
        ("alsatian", "nickname")]


def test_wiki_title_keys_drop_disambiguator_then_dog_suffix():
    assert wiki_title_keys("Chihuahua (dog)") == [("chihuahua dog", "exact"), ("chihuahua", "exact"),
                                                  ("chihuahuadog", "variant")]
    assert wiki_title_keys("Bernese Mountain Dog") == [("bernese mountain dog", "exact"), ("bernese mountain", "variant"),
                                                       ("bernesemountaindog", "variant")]
    assert ("braque francais pyrenean", "variant") in wiki_title_keys("Braque Francais (Pyrenean type)")
    assert ("slovakianwirehairedpointer", "variant") in wiki_title_keys("Slovakian Wire-Haired Pointer")
    assert wiki_name_keys(["Slovenský čuvač", "Toy", "Slovak Chuvach"]) == ["slovensky cuvac", "slovak chuvach"]
