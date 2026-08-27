/**
 * What a seeded tag is called, in every language but English.
 *
 * English is absent on purpose and its absence is enforced by the type:
 * `tags.name` **is** the English name, so a table for it would be the same
 * hundred and five strings stored a second time, in a second repository, with
 * nothing checking that the two agree. `Exclude<Locale, "en">` says that once,
 * and a third language added later has to bring a full table or the build
 * fails.
 *
 * **Looked up by key, never by name.** `TagKey` carries why. A tag the library
 * invented has no key, and neither has a seeded row somebody renamed, so both
 * are shown exactly as typed and this table never reaches them.
 *
 * **`Record<TagKey, string>` is the whole guarantee.** `TagKey` is generated
 * from the backend enum, so a tag added to `PREDEFINED_TAGS` with no German
 * name here is a compile error, which is the property `de.ts` has for messages
 * and the reason it is typed as `Messages`. Regenerate the client first
 * (`bun run api:generate`), or the new key is not in the union yet and the
 * error does not appear.
 *
 * Whole phrases, never assembled from parts: German does not keep English word
 * order. Some entries are deliberately not translations. `Business` and
 * `Economics` are one word apart in English and are the two halves of a
 * standard German split, Betriebswirtschaft and Volkswirtschaft; `Self-Help`
 * is Ratgeber, which is what that shelf is called in a German bookshop; and
 * `Science-Fiction`, `Space Opera`, `Mystery` and `True Crime` are the names
 * the German book trade itself uses. `Folklore` is Volkskunde, which is what
 * DDC 390 is called in German and therefore what the number this tag is
 * suggested from means, rather than Sagen, which would name only the stories.
 *
 * **Two tags can read the same to a German reader, and that is known and not
 * closed.** Tag names are unique on the stored English one, in `create_tag`
 * and in the importer, so a household can invent `Informatik` beside the
 * seeded `Computing` and see two chips with one word on them, one deletable
 * and one not. Before these names existed the two were visibly different
 * words, so this table is what made it possible.
 *
 * It is left open because every fix that fits here is a partial one. Folding a
 * typed name against `tagName` inside `TagPicker` would cover two of the three
 * pickers and not the third: `TagEditor` passes the picker only the tags the
 * book does **not** carry, which is exactly the case where the collision is
 * invisible, and it covers no import at all. Closing it properly means folding
 * against the translated names where uniqueness is actually decided, which is
 * the backend, and that means this table living on the server: a second copy
 * of it, or a move that puts the display language into the API. Both are a
 * bigger decision than a display feature, and the ticket's scope is display
 * only. Whoever picks it up should start there rather than in the picker.
 */

import { Locale } from "../api/generated/model";
import type { TagKey, TagOut } from "../api/generated/model";

/** Every language whose tag names are not already in the database. */
type Translated = Exclude<Locale, typeof Locale.en>;

export const TAG_NAMES: Record<Translated, Record<TagKey, string>> = {
  [Locale.de]: {
    // Type: what kind of thing it is
    fiction: "Belletristik",
    non_fiction: "Sachbuch",
    reference: "Nachschlagewerk",
    textbook: "Lehrbuch",
    anthology: "Anthologie",
    comics: "Comics",
    manga: "Manga",
    play: "Theaterstück",
    essays: "Essays",
    picture_book: "Bilderbuch",

    // Genre: fiction
    adventure: "Abenteuer",
    classic: "Klassiker",
    contemporary_fiction: "Gegenwartsliteratur",
    crime: "Kriminalroman",
    detective: "Detektivroman",
    dystopian: "Dystopie",
    epic_fantasy: "Epische Fantasy",
    fairy_tales: "Märchen",
    fantasy: "Fantasy",
    folklore: "Volkskunde",
    gothic: "Schauerroman",
    graphic_novel: "Graphic Novel",
    historical_fiction: "Historischer Roman",
    horror: "Horror",
    humour: "Humor",
    literary_fiction: "Literarischer Roman",
    magical_realism: "Magischer Realismus",
    mystery: "Mystery",
    mythology: "Mythologie",
    noir: "Noir",
    paranormal: "Übernatürliches",
    poetry: "Lyrik",
    post_apocalyptic: "Postapokalyptisch",
    romance: "Liebesroman",
    satire: "Satire",
    science_fiction: "Science-Fiction",
    short_stories: "Kurzgeschichten",
    space_opera: "Space Opera",
    speculative_fiction: "Spekulative Fiktion",
    spy_fiction: "Spionageroman",
    steampunk: "Steampunk",
    suspense: "Spannung",
    thriller: "Thriller",
    urban_fantasy: "Urban Fantasy",
    war: "Krieg",
    western: "Western",

    // Genre: non-fiction
    anthropology: "Anthropologie",
    archaeology: "Archäologie",
    architecture: "Architektur",
    art: "Kunst",
    astronomy: "Astronomie",
    autobiography: "Autobiografie",
    biography: "Biografie",
    biology: "Biologie",
    business: "Betriebswirtschaft",
    chemistry: "Chemie",
    computing: "Informatik",
    cooking: "Kochen",
    design: "Design",
    diaries_and_letters: "Tagebücher und Briefe",
    economics: "Volkswirtschaft",
    education: "Pädagogik",
    environment: "Umwelt",
    ethics: "Ethik",
    feminism: "Feminismus",
    film_and_tv: "Film und Fernsehen",
    finance: "Finanzen",
    gardening: "Garten",
    geography: "Geografie",
    health_and_fitness: "Gesundheit und Fitness",
    history: "Geschichte",
    journalism: "Journalismus",
    language: "Sprache",
    law: "Recht",
    linguistics: "Sprachwissenschaft",
    mathematics: "Mathematik",
    medicine: "Medizin",
    memoir: "Erinnerungen",
    music: "Musik",
    nature: "Natur",
    parenting: "Kindererziehung",
    philosophy: "Philosophie",
    photography: "Fotografie",
    physics: "Physik",
    politics: "Politik",
    popular_science: "Populärwissenschaft",
    psychology: "Psychologie",
    religion: "Religion",
    science: "Naturwissenschaft",
    self_help: "Ratgeber",
    sociology: "Soziologie",
    sports: "Sport",
    technology: "Technik",
    theatre: "Theater",
    travel: "Reisen",
    true_crime: "True Crime",
    urbanism: "Stadtplanung",
    wine_and_drink: "Wein und Getränke",

    // Age: who it is for
    baby_and_toddler: "Baby und Kleinkind (0-3)",
    children: "Kinder (0-8)",
    early_reader: "Erstleser (5-8)",
    middle_grade: "Kinderbuch (8-12)",
    young_adult: "Jugendbuch (13-18)",
    new_adult: "New Adult (18-25)",
    adult: "Erwachsene",
  },
};

/**
 * What to print for this tag, in this language.
 *
 * The one road to a tag's name on screen, so that a site which forgets it is a
 * site printing English into a German page.
 * `frontend/tests/houseRules.test.ts` asserts nothing outside this module
 * reads `.name` off a tag.
 *
 * Falls back to the stored name for a tag with no key, which is every tag the
 * library invented and every seeded row it renamed, and for a key this build
 * does not know, which is what an older client against a newer API would see.
 */
export function tagName(
  tag: Pick<TagOut, "name" | "key">,
  locale: Locale,
): string {
  // English is the stored name, not a table lookup: see the note above.
  if (locale === Locale.en) return tag.name;
  return (tag.key ? TAG_NAMES[locale][tag.key] : undefined) ?? tag.name;
}
