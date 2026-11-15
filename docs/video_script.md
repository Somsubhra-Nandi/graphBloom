# GraphBloom: 2.5-minute video script

About 340 spoken words. Every number below is in `README.md` and `results/`. Record the demo at 1920 wide, with the page open at the top and no `?fps` badge.

## 0:00–0:20 The problem

**On screen:** Black, then the hero page loads. The graph fades in behind the headline: "A knowledge graph that finds out which facts it is missing."

**Say:**
> To answer questions over documents, you can turn them into a graph of facts.
> But reading every fact out of every document is expensive.
> And most of those facts are never asked about.
> So we start shallow, and let the questions tell us what is missing.

## 0:20–1:20 Live demo

**0:20–0:50. The story.** Let the hero play from the start; the first example is "Who is Publius Licinius Crassus's father-in-law?"

| Time | On screen | Say |
|---|---|---|
| 0:20 | The question card appears; the camera moves in on the first dot. | "Here is a question the graph has never seen." |
| 0:26 | Red pulse, label "missing fact: spouse". | "It follows the links and hits a dead end. There is no spouse link for this person." |
| 0:33 | Green line grows in; label "new link: spouse". | "So it goes back to the source text, reads it for that one kind of link, and adds it." |
| 0:40 | The path completes in green; the answer label appears. | "Now the path reaches an answer." |
| 0:45 | Accuracy card ticks from 47% to 55%. | "And accuracy on unseen questions goes up." |

**0:50–1:20. Replay learning.** Click "Replay learning". The slider moves 0 to 5 by itself; at the end, stop on 5.

| Time | On screen | Say |
|---|---|---|
| 0:50 | Click the button. Graph clears to the starting links. | "This is the whole run, five rounds." |
| 0:55 | Slider at 1; left card lists "father, date of death". | "Round one adds father and date of death, because those are what the failed questions needed." |
| 1:05 | Green links appear between the grey ones; the curve climbs. | "Each round adds a few links, only where questions got stuck." |
| 1:13 | Slider at 5; card says 2,718 links, 137 learned; curve at 57%. | "After five rounds, 137 learned links on top of 2,581 from the first pass. Forty-seven percent became fifty-seven." |

## 1:20–1:50 Results and the honest comparison

**On screen:** Scroll to "Gets better as it's used". The curve draws in; point at the labels.

**Say:**
> This is eighty-seven questions the system never trained on.
> Learned goes from forty-seven to fifty-seven percent. Keyword search alone gets twenty-three.
> Picking links at random also helps, to fifty-two and fifty-three.
> And a version that is simply told the right links up front scores fifty-five, which is within noise of ours.
> So learning doesn't beat knowing the links. It replaces needing to know them.

## 1:50–2:15 Cost and who it is for

**On screen:** Scroll to "Pays only for what's asked". The white line rises, the green lines stay flat. Then pause on the two small cards, "Who it is for" and "Who it is not for".

**Say:**
> Extracting everything up front costs more as your library grows.
> Ours costs more as the questions grow.
> For a million documents and ten thousand questions, that is about twenty-nine percent less.
> It is built for big collections where most documents are rarely asked about: legal discovery, archives, research libraries.
> For a small collection that gets asked about constantly, extracting everything first is cheaper, and we say so.

## 2:15–2:30 Load and engineering

**On screen:** Scroll to "Fast under load", then to the footer with the roadmap and the "Request a pilot" button.

**Say:**
> It stays fast under load: fifty questions at once, while twenty-seven hundred new nodes a second are written. Slowest five percent, two hundred nine milliseconds, no errors.
> Next, we learn from thumbs-down and dead ends, without labelled questions.
> If you have a large archive, ask us for a pilot.

## Notes for recording

- If the first example has already moved on, wait for the cycle to return to it (about 16 seconds per example) or reload the page.
- Say "link" rather than "relation" throughout; it matches the page.
- Don't claim the learned policy beats the open-vocabulary version, or that cost per question is lower; neither is true.
