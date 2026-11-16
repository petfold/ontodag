"""What the film says, scene by scene.

Each scene is a list of lines, and a line is `(id, text)`. The film's
pictures are timed against the ids (`scenes.py`), so a line is the unit a
picture can wait for. Inside a line `|` ends an utterance: each utterance
is spoken on its own and a short pause follows it. An utterance needs four
words or more: the voice murmurs after a shorter one (`voice.py`), so a
short sentence stays joined to its neighbour.

The text is written to be heard, in British English. Nothing here reads
syntax aloud; the screen shows it.
"""

VOICE = "bf_emma"          # Kokoro's British voices: bf_emma, bm_george, ...
SPEED = 0.88               # 1.0 is the voice's own pace

PAUSE = 0.42               # after an utterance, inside a line
LINE_GAP = 0.80            # between the lines of a scene
SCENE_LEAD = 1.40          # a scene's pictures begin; then its first line
SCENE_TAIL = 1.30          # after a scene's last line

# Where the pictures need longer than the usual gap after a line.
AFTER = {
    "r5": 1.9,             # the graph is built again in another order
    "e2": 4.5,             # the last card stays
}

SCENES = [
    ("title", [
        ("i1", "OntoDAG is a store for categories."),
        ("i2", "You file each thing under every category it belongs to. |"
               " Later, you name a few categories, and it gives you"
               " everything that falls under all of them."),
        ("i3", "The idea is small, and OntoDAG keeps it exact. |"
               " Let us build it up, one step at a time."),
    ]),
    ("folders", [
        ("f1", "Here is a flight confirmation, for a trip to Japan. |"
               " Where should it go? |"
               " In the folder for flights, or in the folder for Japan?"),
        ("f2", "Folders make you choose one place. |"
               " And whichever you choose, you will look in the other one"
               " first."),
        ("f3", "Tags are kinder: one thing may carry several. |"
               " But tags know nothing of one another."),
        ("f4", "Tag a scan as a boarding pass, and a search for flights"
               " will miss it, unless you remember to tag it as a flight"
               " as well. Every time."),
    ]),
    ("idea", [
        ("d1", "OntoDAG keeps the good half of each. |"
               " Here are two categories: Flight, and Japan."),
        ("d2", "File the confirmation under both. |"
               " There is nothing to choose."),
        ("d3", "Now the boarding pass. |"
               " It belongs to that flight, so file it under the flight"
               " itself."),
        ("d4", "Anything can have things filed beneath it. |"
               " An item and a category are the same kind of thing."),
        ("d5", "An arrow always means the same: whatever is below also"
               " belongs to what is above. |"
               " So the boarding pass is a flight document, and part of"
               " the Japan trip, although nobody said so."),
        ("d6", "Add a hotel booking, and a flight to Berlin. |"
               " A single root sits above them all."),
        ("d7", "The arrows may meet, so this is not a tree. |"
               " It is a directed acyclic graph, or DAG. |"
               " That is where the name comes from."),
    ]),
    ("question", [
        ("q1", "Everything below a category is its cone."),
        ("q2", "Ask for Japan, and you get its cone: the whole trip,"
               " boarding pass included."),
        ("q3", "Ask for two categories, and you get what lies in both"
               " cones. |"
               " Here, that is the flight to Japan, and its boarding pass. |"
               " Not the hotel, and not the flight to Berlin."),
        ("q4", "That is the whole query language. |"
               " One question: what is below all of these? |"
               " The order of the words does not matter."),
    ]),
    ("rule", [
        ("r1", "One rule holds all this together. |"
               " Keep no link that the others already imply."),
        ("r2", "Try to file the boarding pass under Japan directly, and"
               " nothing changes. | The graph says so already."),
        ("r3", "And no loops."
               " Nothing may end up below itself, so OntoDAG refuses a"
               " link like this one."),
        ("r4", "Why so strict?"
               " Because a graph like this has exactly one smallest form."),
        ("r5", "So build it in any order, with any detours, and the same"
               " knowledge ends in the same shape."),
    ]),
    ("root", [
        ("p1", "One shape can have one fingerprint: a short code, worked"
               " out from the whole store. |"
               " OntoDAG calls it the root."),
        ("p2", "Two people who file the same facts, in any order, get the"
               " same root, to the last character. |"
               " Equal knowledge, equal root."),
        ("p3", "So to compare two stores, you begin by comparing two short"
               " strings."),
    ]),
    ("merge", [
        ("m1", "It also lets people work apart. |"
               " Alice adds a hotel in Kyoto. |"
               " Bob adds a rail pass. |"
               " Neither asks the other."),
        ("m2", "When they merge, each store takes in what the other knows,"
               " and tidies itself by the same rule."),
        ("m3", "Both arrive at the same root. |"
               " No server decides, and the order does not matter. |"
               " Merge again, and nothing changes."),
    ]),
    ("values", [
        ("v1", "Some orderings are too large to draw. |"
               " Take dates."
               " A flight on the fifteenth of August was in August, in the"
               " summer, and in twenty twenty-six."),
        ("v2", "Nobody could file it under every period that contains it."),
        ("v3", "So for values like these, OntoDAG works out the order from"
               " the names themselves. |"
               " File each flight under its day."),
        ("v4", "Then ask for the flights in any stretch of time, even one"
               " that nobody has named. |"
               " OntoDAG computes the answer, and stores no link for it."),
        ("v5", "The same holds for masses and lengths, for sizes, and for"
               " places on a map."),
        ("v6", "And the arithmetic is exact. |"
               " OntoDAG stores five hundred grams as one half of a"
               " kilogram, never as a rounded number. |"
               " So every copy of a store works out the same order."),
    ]),
    ("proof", [
        ("c1", "The root gives one thing more: answers you can prove."),
        ("c2", "Ask whether the boarding pass belongs to the Japan trip. |"
               " The answer can come with a certificate: a few of the"
               " store's own records."),
        ("c3", "Anyone can check it, holding nothing but the root. |"
               " The answer travels. The store stays where it is."),
    ]),
    ("where", [
        ("w1", "A store can live in a plain text file. |"
               " Or in a local record store, which keeps every version. |"
               " Or on the Swarm network, where others can read it."),
        ("w2", "The commands are the same for all three."),
        ("w3", "And one store serves the command line, Python, a browser,"
               " and an AI agent. |"
               " The agent gets the root with every answer, so you can"
               " check what it tells you."),
    ]),
    ("close", [
        ("e1", "One graph, one rule, one question."),
        ("e2", "That is OntoDAG: categories beyond trees."),
    ]),
]


def lines():
    """Every line in order, as (scene id, line id, [utterance, ...])."""
    for scene, entries in SCENES:
        for line_id, text in entries:
            parts = [part.strip() for part in text.split("|")]
            yield scene, line_id, [part for part in parts if part]


def text_of(line_id):
    """A line's text as one string, without the utterance marks."""
    for _, found, parts in lines():
        if found == line_id:
            return " ".join(parts)
    raise KeyError(line_id)


if __name__ == "__main__":
    words = sum(len(" ".join(parts).split()) for _, _, parts in lines())
    print(sum(1 for _ in lines()), "lines,", words, "words")
