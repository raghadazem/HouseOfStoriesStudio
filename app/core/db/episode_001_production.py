"""Episode 001 real production content — Milestone 6.

Populates the already-seeded Episode 001 (``app.core.db.seed``) with
real production content: a full Arabic script, a 15-scene storyboard
with composed prompts, an original song, three Shorts, and a YouTube
SEO package. This is authored content, not a placeholder — but it is
deliberately **not** a substitute for human review: nothing here calls
``ScriptService.submit_script_ready``/``approve_script``, nothing
approves a Scene, and no ``CharacterVersion`` is marked
``approved_canon``. The Images/Video workspace stages are expected to
report **blocked** until a human actually approves reference artwork
for Melissa, Bilsan, and Tortor — see
``docs/30_MILESTONE_6_EPISODE_001_PRODUCTION_STATUS.md``.

Every populate step below is independently idempotent: it only ever
writes to a field that is currently empty. Re-running this against a
database where a human has since edited the script, a scene, the song,
a Short, or the SEO fields through the GUI **changes nothing** for that
already-populated piece — this never resets or overwrites real work,
matching the founder's explicit "never destroy or reset existing
Episode 001 data automatically" rule.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.db.enums import CharacterVersionStatus, PromptCategory, PromptType
from app.core.db.seed import seed_demo_data
from app.core.models import Character, CharacterVersion, Episode, PromptTemplate
from app.core.services.episode_service import EpisodeService
from app.core.services.prompt_template_service import PromptTemplateService
from app.core.services.scene_service import SceneService
from app.core.services.script_service import ScriptService
from app.core.services.short_service import ShortService
from app.core.services.song_service import SongService

logger = logging.getLogger("house_of_stories.episode_001_production")

TORTOR_SLUG = "tortor"
_THUMBNAIL_TEMPLATE_NAME = "ep001_thumbnail_concept"

_PLACEHOLDER_REVIEW_NOTE = (
    "Awaiting approved reference artwork before this version can move to "
    "approved_canon."
)

# Shared across every scene's manually-authored negative prompt, merged
# by PromptComposerService with each character's own locked negative
# prompt (none exist yet — see the module docstring) — encodes the
# World/Brand Bible's "no violence, no frightening scenes" rule directly
# into every composed prompt, not just documentation.
_NEGATIVE_PROMPT_BASELINE = (
    "scary imagery, violence, weapons, dark horror lighting, realistic photography, "
    "adult body proportions"
)

# --------------------------------------------------------------------------- SCRIPT

SCRIPT_SUMMARY_AR = (
    "في نزهة صباحية عند بحيرة الفراشات، تكتشف الأختان ميليسا وبيلسان سلحفاة صغيرة "
    "ضائعة اسمها طُرطُر، ابتعدت عن عائلتها. تنطلق الأختان في رحلة عبر الغابة وجسر "
    "قوس قزح لمساعدة صديقتهما الجديدة على العودة إلى بيتها، ويتعلمان في الطريق أنّ "
    "أصغر مساعدة يمكن أن تصنع أكبر فرق."
)

SCRIPT_FULL_TEXT_AR = """ميليسا وبيلسان والسلحفاة الصغيرة الضائعة
الحلقة الأولى — الدرس: مساعدة الآخرين

المشهد ١ — صوتٌ غريب عند البحيرة
الراوي: في وادي الحكايات، حيث تتكلم الحيوانات، وتبدأ كل صباح مغامرة جديدة...
بيلسان: ميليسا! هل سمعتِ هذا الصوت؟
ميليسا: نعم! يبدو أنّ أحداً يبكي بالقرب من الصخور.

المشهد ٢ — صباح الأختين
الراوي: كل صباح، تذهب ميليسا وبيلسان إلى الغابة معاً، ومعهما الدبدوب الصغير.
ميليسا: هيا يا بيلسان، السماء صافية اليوم!
بيلسان: نعم! أحبّ الذهاب إلى بحيرة الفراشات.

المشهد ٣ — اكتشاف السلحفاة الصغيرة
ميليسا: انظري يا بيلسان! سلحفاة صغيرة، وحيدة بين الصخور!
بيلسان: مسكينة! لماذا تبكين يا سلحفاة صغيرة؟
طُرطُر: لقد ابتعدتُ عن أسرتي... ولا أعرف الطريق إلى بيتي.
ميليسا: لا تخافي، نحن هنا معك.

المشهد ٤ — قرار المساعدة
ميليسا: يا بيلسان، يجب أن نساعد طُرطُر في العثور على أسرتها.
بيلسان: نعم! أنا مستعدة! هيا بنا!
طُرطُر: شكراً لكما... أنتما لطيفتان جداً.
الراوي: وهكذا، قررت الأختان أن تبدآ رحلة مساعدة صديقتهما الجديدة.

المشهد ٥ — سؤال الغابة
بيلسان: أيها العصفور الصغير، هل رأيت أسرة السلحفاة؟
العصفور: سمعتُ أصواتاً قرب جسر قوس قزح، هناك بركة هادئة.
ميليسا: شكراً أيها العصفور! هيا يا بيلسان، إلى الجسر!

المشهد ٦ — عبور جسر قوس قزح
الراوي: في طريقهم، وجدوا جذع شجرة كبير يغلق الطريق.
بيلسان: كيف سنعبر يا ميليسا؟
ميليسا: بهدوء... وخطوة خطوة. أمسكي يدي يا بيلسان.

المشهد ٧ — لحظة مضحكة
طُرطُر: هاها! دبدوبك يحب اللعب في العشب!
بيلسان: هو مشاغب مثلي تماماً!
ميليسا: أنتما الاثنان مضحكان جداً!

المشهد ٨ — لحظة حزينة صغيرة
طُرطُر: أشتاق كثيراً إلى أمي وإخوتي...
بيلسان: لا تحزني، سنجد عائلتك معاً.
ميليسا: نحن أصدقاؤك الآن، ولن نتركك وحيدة.
طُرطُر: شكراً لكما... هذا يجعلني أشعر بالأمان.

المشهد ٩ — أغنية "معاً نستطيع"
ميليسا وبيلسان: معاً معاً، نستطيع، خطوة خطوة نتابع
طُرطُر: يد بيد، قلب بقلب، ما أجمل أن نتعاون
الجميع: معاً نستطيع! معاً نستطيع! كل شيء بالتعاون يصبح سريع!

المشهد ١٠ — عائق الطريق
بيلسان: انظري! غصن كبير يمنعنا من الوصول!
طُرطُر: بركة عائلتي خلف هذا الغصن مباشرة!
ميليسا: لا تقلقي، سنجد حلاً معاً.

المشهد ١١ — العمل معاً
ميليسا: هيا يا بيلسان، بيدين تصبح القوة أكبر!
بيلسان: واحد، اثنان، ثلاثة... ادفعي!
طُرطُر: نجحنا! أرى البركة!

المشهد ١٢ — لمّ الشمل
أم السلحفاة: طُرطُر! يا صغيرتي! أين كنتِ؟
طُرطُر: أمي! لقد ساعدتني ميليسا وبيلسان في العودة إليكِ!

المشهد ١٣ — الدرس
ميليسا: أتعرفين يا بيلسان؟ عندما نساعد الآخرين، نشعر بسعادة كبيرة.
بيلسان: نعم! ولو كانت المساعدة صغيرة، فهي تعني الكثير.
أم السلحفاة: شكراً لكما يا صغيرتيّ، لن ننسى لطفكما أبداً.

المشهد ١٤ — عودة دافئة
الراوي: عادت ميليسا وبيلسان إلى بيتهما، وقلباهما مليئان بالفرح.
بيلسان: كان يوماً رائعاً يا ميليسا!
ميليسا: نعم، لأننا ساعدنا صديقة جديدة.

المشهد ١٥ — تشويق للمغامرة القادمة
بيلسان: ميليسا، انظري! ما هذا الضوء اللامع هناك؟
ميليسا: لا أعرف... لكن يبدو أنّ مغامرة جديدة تنتظرنا!
الراوي: ما الذي يخبئه ضوء حديقة القمر؟ انتظرونا في الحلقة القادمة!
"""

SCRIPT_NOTES = (
    "Draft v1 — full first-pass script for Episode 001, written to the approved "
    "Character Bible (docs/02) and World Bible (docs/03) constraints: no violence, "
    "no frightening scenes, one clear lesson (helping others), ages 3-7, simple "
    "White Arabic throughout. Awaiting human review via the Script tab's Mark "
    "Ready / Approve workflow before production treats it as final — this "
    "population step never marks it ready or approved programmatically."
)

# --------------------------------------------------------------------------- SCENES
#
# Each scene's ``dialogue_ar`` is that scene's excerpt of the full script
# above, kept in the "Speaker: line" convention SceneService.build_voice_package
# parses. ``description``/``camera_direction`` are in English (standard
# prompt-engineering practice for image/video generators, matching how
# app.core.db.seed already writes Melissa/Bilsan's visual_summary in
# English even though their dialogue is Arabic). Narrative beat (Hook /
# Introduction / Discovery / ...) is noted in each comment for traceability
# back to the founder's 12-beat structure; it is not a stored field —
# Scene has no "purpose" column, and title/description already carry
# enough context for production, so one wasn't added (see
# docs/30_MILESTONE_6_EPISODE_001_PRODUCTION_STATUS.md).

_M = "melissa"
_B = "bilsan"
_T = "tortor"

SCENES: list[dict[str, object]] = [
    {  # 1. Hook
        "title": "صوت غريب عند البحيرة",
        "location": "Butterfly Lake",
        "description": (
            "Sunrise at Butterfly Lake — golden light glinting off calm water, reeds and "
            "lily pads along the shore, colorful butterflies drifting above the water. "
            "Melissa and Bilsan stand at the water's edge, Bilsan hugging her small teddy "
            "bear, both looking toward a rustling patch of reeds with curious expressions."
        ),
        "camera_direction": (
            "Wide establishing shot of Butterfly Lake at sunrise, slow push-in toward the "
            "reeds. Cut to close-up on Bilsan's curious face on her line."
        ),
        "voice_notes": (
            "Bilsan: curious, slightly startled. Melissa: calm and attentive. Keep pacing "
            "slow to build gentle mystery — this is a hook, not a scare."
        ),
        "dialogue_ar": (
            "الراوي: في وادي الحكايات، حيث تتكلم الحيوانات، وتبدأ كل صباح مغامرة جديدة...\n"
            "بيلسان: ميليسا! هل سمعتِ هذا الصوت؟\n"
            "ميليسا: نعم! يبدو أنّ أحداً يبكي بالقرب من الصخور."
        ),
        "estimated_duration_seconds": 25,
        "character_slugs": [_M, _B],
    },
    {  # 2. Introduction
        "title": "صباح الأختين",
        "location": "Melissa and Bilsan's Cottage Garden",
        "description": (
            "A cozy cottage garden — flowerbeds, a small wooden fence, morning sunlight. "
            "Melissa in her denim dress and Bilsan in her purple dress walk hand in hand "
            "toward the garden gate, Bilsan carrying her teddy bear."
        ),
        "camera_direction": (
            "Medium shot, sisters walking through the garden gate, camera tracks alongside "
            "them. Cut to wide shot of the lake path as they exit."
        ),
        "voice_notes": "Warm, playful morning energy. Natural sisterly banter pace — quick but soft.",
        "dialogue_ar": (
            "الراوي: كل صباح، تذهب ميليسا وبيلسان إلى الغابة معاً، ومعهما الدبدوب الصغير.\n"
            "ميليسا: هيا يا بيلسان، السماء صافية اليوم!\n"
            "بيلسان: نعم! أحبّ الذهاب إلى بحيرة الفراشات."
        ),
        "estimated_duration_seconds": 30,
        "character_slugs": [_M, _B],
    },
    {  # 3. Discovery of the lost turtle
        "title": "اكتشاف السلحفاة الصغيرة",
        "location": "Butterfly Lake",
        "description": (
            "Smooth lake-side rocks with small tide pools. A tiny lost turtle (Tortor) "
            "wedged gently between two rocks, looking small and frightened, with big round "
            "eyes. Melissa and Bilsan kneel beside her, Melissa reaching out a gentle, "
            "reassuring hand."
        ),
        "camera_direction": (
            "Close-up on the turtle wedged between rocks, then reverse shot to Melissa and "
            "Bilsan crouching down. Slow zoom on Tortor's face on her line. Cut to two-shot "
            "of the sisters on Melissa's reassurance."
        ),
        "voice_notes": (
            "Tortor's first line: small, trembling, quiet — a whisper that grows slightly "
            "steadier by her second line. Melissa: reassuring, warm, slower pace than her "
            "usual energetic tone."
        ),
        "dialogue_ar": (
            "ميليسا: انظري يا بيلسان! سلحفاة صغيرة، وحيدة بين الصخور!\n"
            "بيلسان: مسكينة! لماذا تبكين يا سلحفاة صغيرة؟\n"
            "طُرطُر: لقد ابتعدتُ عن أسرتي... ولا أعرف الطريق إلى بيتي.\n"
            "ميليسا: لا تخافي، نحن هنا معك."
        ),
        "estimated_duration_seconds": 40,
        "character_slugs": [_M, _B, _T],
    },
    {  # 4. Decision to help
        "title": "قرار المساعدة",
        "location": "Butterfly Lake",
        "description": (
            "The same lakeside rocks. Melissa cradles Tortor carefully in her hands while "
            "Bilsan pats the turtle's shell gently, teddy bear tucked under her other arm. "
            "Warm, determined expressions on both sisters' faces."
        ),
        "camera_direction": (
            "Two-shot of Melissa and Bilsan with Tortor cradled between them, camera holds "
            "steady for the promise. Cut to wide shot as narrator speaks, group beginning "
            "to walk."
        ),
        "voice_notes": (
            "Bilsan: enthusiastic, quick pace. Tortor: relieved, grateful, softer volume. "
            "Narrator: warm, storytelling pace, slightly slower than dialogue."
        ),
        "dialogue_ar": (
            "ميليسا: يا بيلسان، يجب أن نساعد طُرطُر في العثور على أسرتها.\n"
            "بيلسان: نعم! أنا مستعدة! هيا بنا!\n"
            "طُرطُر: شكراً لكما... أنتما لطيفتان جداً.\n"
            "الراوي: وهكذا، قررت الأختان أن تبدآ رحلة مساعدة صديقتهما الجديدة."
        ),
        "estimated_duration_seconds": 30,
        "character_slugs": [_M, _B, _T],
    },
    {  # 5. Search/adventure (part 1)
        "title": "سؤال الغابة",
        "location": "The Forest",
        "description": (
            "A sunlit forest clearing with tall trees and dappled light. A small colorful "
            "bird perched on a low branch, addressing Melissa and Bilsan who stand below, "
            "Tortor held safely in Melissa's arms."
        ),
        "camera_direction": (
            "Medium shot in the forest, bird perched on a low branch in frame with the "
            "sisters below. Slight upward tilt to the bird on its line. Cut to wide "
            "tracking shot heading toward the bridge."
        ),
        "voice_notes": "Bird: bright, chirpy, slightly faster pace (birdlike energy). Melissa: encouraging, upbeat.",
        "dialogue_ar": (
            "بيلسان: أيها العصفور الصغير، هل رأيت أسرة السلحفاة؟\n"
            "العصفور: سمعتُ أصواتاً قرب جسر قوس قزح، هناك بركة هادئة.\n"
            "ميليسا: شكراً أيها العصفور! هيا يا بيلسان، إلى الجسر!"
        ),
        "estimated_duration_seconds": 45,
        "character_slugs": [_M, _B, _T],
    },
    {  # 6. Search/adventure (part 2)
        "title": "عبور جسر قوس قزح",
        "location": "Rainbow Bridge",
        "description": (
            "Rainbow Bridge — a whimsical wooden bridge arched with faint rainbow-colored "
            "light, spanning a small forest stream. A large fallen tree log blocks the "
            "crossing. Melissa leads the way holding Bilsan's hand, Tortor tucked safely "
            "against Bilsan's side."
        ),
        "camera_direction": (
            "Wide shot of Rainbow Bridge and the fallen log, camera pans slowly left to "
            "right revealing the obstacle. Medium tracking shot following the group's "
            "careful crossing, hand-holding visible in frame. Cut to grassy clearing on "
            "the far side."
        ),
        "voice_notes": (
            "Cautious, careful pacing on 'بهدوء... وخطوة خطوة' — pause briefly between the "
            "two phrases for suspense-free care, not fear."
        ),
        "dialogue_ar": (
            "الراوي: في طريقهم، وجدوا جذع شجرة كبير يغلق الطريق.\n"
            "بيلسان: كيف سنعبر يا ميليسا؟\n"
            "ميليسا: بهدوء... وخطوة خطوة. أمسكي يدي يا بيلسان."
        ),
        "estimated_duration_seconds": 45,
        "character_slugs": [_M, _B, _T],
    },
    {  # 7. Small funny moment
        "title": "لحظة مضحكة",
        "location": "Forest Clearing (past Rainbow Bridge)",
        "description": (
            "Tall soft grass on the far side of the bridge. Bilsan mid-trip, teddy bear "
            "flying gently from her hand, comedic motion lines, everyone's expressions "
            "bright and joyful rather than alarmed. Tortor peeking out with a wide, "
            "delighted smile."
        ),
        "camera_direction": (
            "Medium-wide shot, Bilsan trips into frame from the right, gentle comedic "
            "timing on the fall. Cut to close-up on Tortor's laughing face, then a two-shot "
            "for the group laugh."
        ),
        "voice_notes": (
            "Comedic beat: Tortor's laugh should be light and genuine, not mocking. "
            "Bilsan's line delivered with a giggle mid-sentence."
        ),
        "dialogue_ar": (
            "طُرطُر: هاها! دبدوبك يحب اللعب في العشب!\n"
            "بيلسان: هو مشاغب مثلي تماماً!\n"
            "ميليسا: أنتما الاثنان مضحكان جداً!"
        ),
        "estimated_duration_seconds": 30,
        "character_slugs": [_M, _B, _T],
    },
    {  # 8. Emotional moment
        "title": "لحظة حزينة صغيرة",
        "location": "Under a Forest Tree",
        "description": (
            "Underneath a large shady tree, soft afternoon light. The group sits together "
            "in a small circle. Tortor looks down with a wistful expression; Bilsan wraps "
            "a gentle arm around her, teddy bear resting beside them; Melissa leans in "
            "warmly."
        ),
        "camera_direction": (
            "Close two-shot under the tree, soft warm lighting, slow static camera to let "
            "the emotional beat breathe. Slow push-in on Tortor during her admission. Cut "
            "to wide shot as the group rests."
        ),
        "voice_notes": (
            "Tortor: quiet, wistful, near-tears but not sobbing — gentle sadness "
            "appropriate for ages 3-7. Bilsan and Melissa: soft, comforting, slower pace, "
            "warm tone throughout."
        ),
        "dialogue_ar": (
            "طُرطُر: أشتاق كثيراً إلى أمي وإخوتي...\n"
            "بيلسان: لا تحزني، سنجد عائلتك معاً.\n"
            "ميليسا: نحن أصدقاؤك الآن، ولن نتركك وحيدة.\n"
            "طُرطُر: شكراً لكما... هذا يجعلني أشعر بالأمان."
        ),
        "estimated_duration_seconds": 35,
        "character_slugs": [_M, _B, _T],
    },
    {  # 9. Original short song
        "title": "أغنية معاً نستطيع",
        "location": "Meadow Path toward Moon Garden",
        "description": (
            "The group walking together through a flower-dotted meadow path toward Moon "
            "Garden, golden late-afternoon light, motion lines suggesting a cheerful skip "
            "in their step, small musical notes floating decoratively in the air around "
            "them."
        ),
        "camera_direction": (
            "Dynamic tracking shot following the group as they walk and sing, alternating "
            "close-ups on each singer during their line, wide group shot for the chorus. "
            "Cut to Moon Garden's edge as the song ends."
        ),
        "voice_notes": "Sung, not spoken — see the Song package for full musical direction. Bright and joyful.",
        "dialogue_ar": (
            "ميليسا وبيلسان: معاً معاً، نستطيع، خطوة خطوة نتابع\n"
            "طُرطُر: يد بيد، قلب بقلب، ما أجمل أن نتعاون\n"
            "الجميع: معاً نستطيع! معاً نستطيع! كل شيء بالتعاون يصبح سريع!"
        ),
        "estimated_duration_seconds": 60,
        "character_slugs": [_M, _B, _T],
    },
    {  # 10. Solution (obstacle)
        "title": "عائق الطريق",
        "location": "Moon Garden Edge",
        "description": (
            "The edge of Moon Garden — pale, moonflower-dotted plants glowing faintly even "
            "in daylight. A large fallen branch blocks a narrow dirt path leading to a "
            "hidden pond just visible beyond it. The group stands studying the obstacle."
        ),
        "camera_direction": (
            "Wide shot revealing the fallen branch blocking the pond path. Medium shot on "
            "Tortor's hopeful/urgent reaction. Cut to two-shot of the sisters conferring."
        ),
        "voice_notes": "Bilsan: mild concern, not fear. Tortor: hopeful, a little urgent. Melissa: steady, reassuring.",
        "dialogue_ar": (
            "بيلسان: انظري! غصن كبير يمنعنا من الوصول!\n"
            "طُرطُر: بركة عائلتي خلف هذا الغصن مباشرة!\n"
            "ميليسا: لا تقلقي، سنجد حلاً معاً."
        ),
        "estimated_duration_seconds": 45,
        "character_slugs": [_M, _B, _T],
    },
    {  # 11. Solution (teamwork)
        "title": "العمل معاً",
        "location": "Moon Garden Edge",
        "description": (
            "The group lined up together pushing the large fallen branch with visible team "
            "effort — Melissa and Bilsan's hands braced against the wood, Tortor cheering "
            "them on from a safe distance. The branch mid-roll, path opening beyond."
        ),
        "camera_direction": (
            "Wide shot of the group pushing the branch together, camera holds low and "
            "steady for a sense of teamwork effort. Cut to a satisfying wide shot as the "
            "branch rolls aside and the pond is revealed."
        ),
        "voice_notes": (
            "Energetic teamwork chant on 'واحد، اثنان، ثلاثة' — count clearly and "
            "rhythmically, like a real team effort. Tortor's final line: bright, excited, "
            "faster pace."
        ),
        "dialogue_ar": (
            "ميليسا: هيا يا بيلسان، بيدين تصبح القوة أكبر!\n"
            "بيلسان: واحد، اثنان، ثلاثة... ادفعي!\n"
            "طُرطُر: نجحنا! أرى البركة!"
        ),
        "estimated_duration_seconds": 35,
        "character_slugs": [_M, _B, _T],
    },
    {  # 12. Solution (reunion)
        "title": "لمّ الشمل",
        "location": "Moon Garden Pond",
        "description": (
            "A tranquil moonflower-ringed pond glowing softly in twilight, several turtles "
            "of varying sizes resting on lily pads and rocks. A larger turtle (Tortor's "
            "mother) turns toward Tortor with open, welcoming flippers as Tortor rushes to "
            "her."
        ),
        "camera_direction": (
            "Wide shot of the turtle family pond, camera pushes in as the turtle mother "
            "notices Tortor. Close-up on the reunion embrace. Cut to a warm two-shot of the "
            "smiling sisters watching."
        ),
        "voice_notes": (
            "Turtle mother: warm, relieved, slightly emotional but joyful, not weepy. "
            "Tortor: happy, relieved, quick and warm."
        ),
        "dialogue_ar": (
            "أم السلحفاة: طُرطُر! يا صغيرتي! أين كنتِ؟\n"
            "طُرطُر: أمي! لقد ساعدتني ميليسا وبيلسان في العودة إليكِ!"
        ),
        "estimated_duration_seconds": 35,
        "character_slugs": [_M, _B, _T],
    },
    {  # 13. Lesson
        "title": "الدرس",
        "location": "Moon Garden Pond",
        "description": (
            "The group seated together at the pond's edge in the soft blue-gold light of "
            "early evening, calm and content expressions, turtle family gathered nearby, "
            "teddy bear resting in Bilsan's lap."
        ),
        "camera_direction": (
            "Gentle, static wide shot of the group seated by the pond at dusk, soft golden "
            "light. Hold on each speaker in turn with minimal camera movement to keep "
            "focus on the dialogue."
        ),
        "voice_notes": (
            "Reflective, gentle pace — this is the lesson beat, let the pause between "
            "lines land. Turtle mother: sincere, warm gratitude."
        ),
        "dialogue_ar": (
            "ميليسا: أتعرفين يا بيلسان؟ عندما نساعد الآخرين، نشعر بسعادة كبيرة.\n"
            "بيلسان: نعم! ولو كانت المساعدة صغيرة، فهي تعني الكثير.\n"
            "أم السلحفاة: شكراً لكما يا صغيرتيّ، لن ننسى لطفكما أبداً."
        ),
        "estimated_duration_seconds": 30,
        "character_slugs": [_M, _B, _T],
    },
    {  # 14. Warm ending
        "title": "عودة دافئة",
        "location": "Path Home",
        "description": (
            "A warm sunset path leading back toward the cottage, long soft shadows, "
            "Melissa and Bilsan walking together hand in hand, both smiling contentedly, "
            "teddy bear held snugly."
        ),
        "camera_direction": (
            "Wide tracking shot of the sisters walking home along a sunset path, warm "
            "backlighting. Cut to their front door as they arrive."
        ),
        "voice_notes": "Content, calm, contented pace. Warm sunset-scene energy — slower than the episode's adventure scenes.",
        "dialogue_ar": (
            "الراوي: عادت ميليسا وبيلسان إلى بيتهما، وقلباهما مليئان بالفرح.\n"
            "بيلسان: كان يوماً رائعاً يا ميليسا!\n"
            "ميليسا: نعم، لأننا ساعدنا صديقة جديدة."
        ),
        "estimated_duration_seconds": 30,
        "character_slugs": [_M, _B],
    },
    {  # 15. Teaser for the next adventure
        "title": "تشويق للمغامرة القادمة",
        "location": "Cottage Doorstep",
        "description": (
            "The sisters' front doorstep at dusk, porch light glowing warmly. In the far "
            "background, a soft mysterious glow shimmers among the silhouetted shapes of "
            "Moon Garden, small and intriguing rather than ominous."
        ),
        "camera_direction": (
            "Medium shot of the sisters on the doorstep, camera slowly tilts toward the "
            "distant glow in Moon Garden. Hold on the glow for the teaser beat before "
            "fading to the end card."
        ),
        "voice_notes": (
            "Bilsan: curious, wondering, rising intonation on the question. Melissa: "
            "intrigued, warm mystery (not scary). Narrator: inviting, playful tease for "
            "next episode, slightly faster pace to build anticipation."
        ),
        "dialogue_ar": (
            "بيلسان: ميليسا، انظري! ما هذا الضوء اللامع هناك؟\n"
            "ميليسا: لا أعرف... لكن يبدو أنّ مغامرة جديدة تنتظرنا!\n"
            "الراوي: ما الذي يخبئه ضوء حديقة القمر؟ انتظرونا في الحلقة القادمة!"
        ),
        "estimated_duration_seconds": 20,
        "character_slugs": [_M, _B],
    },
]

# --------------------------------------------------------------------------- SONG

SONG_LYRICS_AR = """معاً نستطيع

(المقطع الأول — ميليسا وبيلسان)
معاً معاً، خطوة خطوة
نمشي في الدرب، بلا صعوبة
يدٌ بيد، وقلبٌ بقلب
نحو الأمل، نحو الحب

(اللازمة — الجميع)
معاً نستطيع! معاً نستطيع!
كل شيء بالتعاون، يصبح سريع
معاً نستطيع! معاً نستطيع!
الحب يجمعنا جميعاً في الربيع

(المقطع الثاني — طُرطُر)
كنتُ خائفة، وحيدة أسير
لكنّ صديقاتي، جعلن قلبي كبير

(اللازمة — الجميع)
معاً نستطيع! معاً نستطيع!
كل شيء بالتعاون، يصبح سريع
معاً نستطيع! معاً نستطيع!
الحب يجمعنا جميعاً في الربيع

(الخاتمة — الجميع)
معاً... معاً... نستطيع!"""

SONG_PURPOSE = (
    "Reinforces the episode's lesson (helping others / teamwork) through a simple, "
    "repetitive sing-along chorus performed by Melissa, Bilsan, and Tortor midway "
    "through the search (Scene 9) — designed to be catchy enough for young viewers "
    "to sing along to on a rewatch."
)

SONG_DURATION_SECONDS = 60

SONG_PRODUCTION_NOTES = (
    "Tempo: upbeat, moderate (~100 BPM), major key, playful children's-choir "
    "instrumentation (ukulele, hand claps, light percussion). Melissa and Bilsan "
    "share the first verse; Tortor sings the second verse in a smaller, "
    "higher-pitched voice that grows more confident by the final chorus. All three "
    "voices join for the chorus and outro. Fully original melody and words — no "
    "instrumentation or lyrics resembling any existing copyrighted song."
)

SONG_SUNO_STYLE_PROMPT = (
    "Children's animated sing-along, warm acoustic pop, ukulele and light "
    "hand-claps, gentle major key, upbeat but soft tempo (~100 BPM), sweet innocent "
    "female child vocals (two young girls trading verses, joined by a small "
    "higher-pitched voice for a supporting character), simple repetitive sing-along "
    "chorus, Arabic lyrics, joyful and heartwarming, clean family-friendly "
    "production, no distortion."
)

# --------------------------------------------------------------------------- SHORTS
#
# Keyed by short_index (matches the 3 PLANNED Shorts app.core.db.seed already
# creates for Episode 001) — "fields" go straight through
# ShortService.update_short's allowlist; "source_scene_order_indexes" are
# linked via ShortService.link_source_scenes.

_COMMON_HASHTAGS = [
    "بيت_الحكايات", "ميليسا_وبيلسان", "قصص_اطفال_بالعربي", "HouseOfStories",
]

SHORTS: dict[int, dict[str, object]] = {
    1: {
        "source_scene_order_indexes": [1, 3],
        "fields": {
            "title_ar": "الاكتشاف!",
            "working_title_en": "The Discovery!",
            "hook_ar": "سلحفاة صغيرة... وحيدة تماماً. ماذا سيحدث بعد ذلك؟",
            "caption_ar": (
                "هل ستساعد ميليسا وبيلسان هذه السلحفاة الصغيرة الضائعة؟ 🐢 شاهدوا "
                "الحلقة الكاملة من بيت الحكايات! 💛"
            ),
            "hashtags": [*_COMMON_HASHTAGS, "سلحفاة"],
            "source_timestamp_range": "00:00–00:25, 00:55–01:35",
            "spoken_text_ar": (
                "بيلسان: ميليسا! هل سمعتِ هذا الصوت؟\n"
                "ميليسا: انظري يا بيلسان! سلحفاة صغيرة، وحيدة بين الصخور!\n"
                "طُرطُر: لقد ابتعدتُ عن أسرتي... ولا أعرف الطريق إلى بيتي."
            ),
            "on_screen_text_ar": "سلحفاة صغيرة... ضائعة! 🐢💔",
            "target_duration_seconds": 30,
            "editing_notes": (
                "Fast cold-open cut directly from Scene 1's mysterious sound to Scene "
                "3's discovery reveal, skipping Scene 2 entirely. Freeze-frame on "
                "Tortor's face with a soft 'aww' sound sting. End on a text-card CTA "
                "to watch the full episode."
            ),
        },
    },
    2: {
        "source_scene_order_indexes": [9],
        "fields": {
            "title_ar": "أغنية معاً نستطيع",
            "working_title_en": "Together We Can (Song Clip)",
            "hook_ar": "أغنية جديدة وممتعة... هل تستطيعون الغناء معنا؟ 🎶",
            "caption_ar": (
                "أغنية جديدة وممتعة عن التعاون من بيت الحكايات! 🎶 غنّوا معنا: معاً "
                "نستطيع! 💛"
            ),
            "hashtags": [*_COMMON_HASHTAGS, "اغنية_اطفال"],
            "source_timestamp_range": "04:40–05:40",
            "spoken_text_ar": (
                "معاً نستطيع! معاً نستطيع! كل شيء بالتعاون، يصبح سريع! معاً نستطيع! "
                "معاً نستطيع! الحب يجمعنا جميعاً في الربيع!"
            ),
            "on_screen_text_ar": "معاً نستطيع! 🎶",
            "target_duration_seconds": 40,
            "editing_notes": (
                "Trim the full ~60s song scene down to the strongest chorus "
                "repetitions (~40s). Add karaoke-style animated on-screen lyrics "
                "synced to the vocal. Loop-friendly ending so it can auto-repeat."
            ),
        },
    },
    3: {
        "source_scene_order_indexes": [11, 12],
        "fields": {
            "title_ar": "لمّ الشمل",
            "working_title_en": "The Reunion",
            "hook_ar": "بعد كل هذه المساعدة... هل ستصل السلحفاة إلى بيتها أخيراً؟",
            "caption_ar": (
                "بعد رحلة طويلة مليئة بالمساعدة... هل وصلت السلحفاة الصغيرة إلى "
                "عائلتها؟ 🥹💛 شاهدوا الحلقة الكاملة!"
            ),
            "hashtags": [*_COMMON_HASHTAGS, "مساعدة_الاخرين"],
            "source_timestamp_range": "06:25–07:35",
            "spoken_text_ar": (
                "بيلسان: واحد، اثنان، ثلاثة... ادفعي!\n"
                "طُرطُر: نجحنا! أرى البركة!\n"
                "أم السلحفاة: طُرطُر! يا صغيرتي! أين كنتِ؟"
            ),
            "on_screen_text_ar": "نجحنا معاً! 🐢💛",
            "target_duration_seconds": 40,
            "editing_notes": (
                "Combine the teamwork push (Scene 11) with the reunion (Scene 12) "
                "into one uplifting emotional beat; add a gentle music swell on the "
                "reunion embrace; end on a warm freeze-frame."
            ),
        },
    },
}

# --------------------------------------------------------------------------- SEO

SEO_DESCRIPTION_AR = (
    "في هذه الحلقة من بيت الحكايات 💛، تكتشف الأختان ميليسا وبيلسان سلحفاة صغيرة "
    "ضائعة بالقرب من بحيرة الفراشات. تنطلق الأختان في رحلة مليئة بالمرح والتعاون "
    "لمساعدة صديقتهما الجديدة على العودة إلى عائلتها. حلقة دافئة عن قيمة مساعدة "
    "الآخرين، مناسبة للأطفال من سنّ ٣ إلى ٧ سنوات.\n\n"
    "اشتركوا في القناة لمتابعة مغامرات جديدة من وادي الحكايات كل أسبوع! 🌈"
)

SEO_DESCRIPTION_EN = (
    "In this House of Stories episode, sisters Melissa and Bilsan discover a tiny "
    "lost turtle near Butterfly Lake. Together with their new friend, they set off "
    "on a warm, gentle adventure to help her find her way home — learning along the "
    "way that even small acts of kindness make a big difference. A heartwarming "
    "episode about helping others, made for children ages 3-7.\n\n"
    "Subscribe for new adventures from the Valley of Tales every week! 🌈"
)

SEO_HASHTAGS = [*_COMMON_HASHTAGS, "مساعدة_الاخرين", "ArabicKidsShow"]

SEO_CREDITS_TEXT = (
    "Written and produced by House of Stories Studio. Characters: Melissa, Bilsan, "
    "and Tortor (House of Stories original characters). Song 'معاً نستطيع' "
    "(Together We Can): original composition, lyrics by House of Stories Studio — "
    "music production pending. No AI-generated or third-party imagery used in this "
    "milestone; all visual assets are pending approved character reference artwork."
)

THUMBNAIL_CONCEPT_TEXT = (
    "CONCEPT: Melissa and Bilsan crouched together at the edge of Butterfly Lake, "
    "both smiling warmly down at Tortor the tiny turtle cupped gently in Melissa's "
    "hands. Bright saturated daylight, warm golden-hour rim lighting, big expressive "
    "eyes on all three characters, colorful butterflies drifting in the background. "
    "Composition leaves clear space in the top third for overlay text and keeps the "
    "characters centered and large enough to read at mobile thumbnail size. Visual "
    "style matches the brand's 'original stylized 3D animation, warm colors, "
    "expressive characters' (docs/01_BRAND_BIBLE.md).\n\n"
    "ARABIC OVERLAY TEXT: مغامرة إنقاذ السلحفاة الصغيرة! 🐢💛\n\n"
    "PROMPT: Bold, rounded, friendly Arabic typography across the top reading "
    "'مغامرة إنقاذ السلحفاة الصغيرة! 🐢💛' in warm yellow with a soft white outline "
    "for readability at small sizes, over the concept described above.\n\n"
    "STATUS: BLOCKED — cannot be rendered as a final thumbnail asset until Melissa "
    "and Bilsan have an approved, active CharacterVersion with real reference "
    "artwork. This is a written concept/prompt only; no image has been generated."
)


def _get_or_create_tortor(session: Session) -> Character:
    """Seed Tortor, Episode 001's supporting character — a lost baby turtle.

    Kept out of ``app.core.db.seed`` deliberately: ``seed_demo_data`` is
    generic dev/demo bootstrap data with its own tested contract (exactly
    2 characters); Tortor is real content specific to this episode. Built
    the same way ``seed_melissa``/``seed_bilsan`` are — a draft,
    unapproved v01 Character Lock, since no approved artwork exists yet.
    """
    existing = session.query(Character).filter_by(slug=TORTOR_SLUG).one_or_none()
    if existing is not None:
        return existing

    character = Character(
        slug=TORTOR_SLUG,
        name_ar="طُرطُر",
        name_en="Tortor",
        age=1,
        role="supporting character — a lost baby turtle",
        traits=["gentle", "shy at first", "brave by the end", "loves her family"],
    )
    session.add(character)
    session.flush()

    version = CharacterVersion(
        character_id=character.id,
        version_number="v01",
        outfit_version="v01",
        description_of_change=(
            "Initial baseline for Episode 001's supporting character; no approved "
            "artwork yet."
        ),
        visual_summary=(
            "A small turtle with a warm green-and-yellow shell, big round eyes, and "
            "an expressive, gentle face — an original design, not based on any "
            "existing character. PLACEHOLDER pending approved animated model-sheet "
            "art — do not treat as final."
        ),
        color_palette=[],
        allowed_accessories=[],
        relative_height=None,
        master_prompt=None,
        negative_prompt=None,
        status=CharacterVersionStatus.DRAFT,
        review_notes=_PLACEHOLDER_REVIEW_NOTE,
    )
    session.add(version)
    session.flush()
    return character


def _populate_script(session: Session, episode: Episode) -> None:
    script_service = ScriptService()
    script = script_service.get_or_create_script(session, episode.id)
    if script.full_script and script.full_script.strip():
        return
    script_service.update_script(
        session, script.id,
        summary=SCRIPT_SUMMARY_AR, full_script=SCRIPT_FULL_TEXT_AR, notes=SCRIPT_NOTES,
    )


def _populate_scenes(
    session: Session, episode: Episode, melissa: Character, bilsan: Character, tortor: Character
) -> None:
    scene_service = SceneService()
    if scene_service.list_episode_scenes(session, episode.id):
        return  # never re-author an existing storyboard

    slug_to_character = {_M: melissa, _B: bilsan, _T: tortor}
    for entry in SCENES:
        character_ids = [slug_to_character[slug].id for slug in entry["character_slugs"]]
        scene = scene_service.add_scene(
            session, episode.id,
            title=entry["title"],
            location=entry["location"],
            description=entry["description"],
            dialogue_ar=entry["dialogue_ar"],
            camera_direction=entry["camera_direction"],
            estimated_duration_seconds=entry["estimated_duration_seconds"],
            character_ids=character_ids,
        )
        scene_service.update_scene(
            session, scene.id,
            voice_notes=entry["voice_notes"],
            negative_prompt_text=_NEGATIVE_PROMPT_BASELINE,
        )
        # Real PromptComposerService composition, not hand-written text —
        # with no approved CharacterVersion yet, this truthfully omits any
        # locked character appearance data (see the module docstring).
        scene_service.generate_and_store_prompt(session, scene.id)


def _populate_song(session: Session, episode: Episode) -> None:
    song_service = SongService()
    song = song_service.get_or_create_song(session, episode.id)
    if song.lyrics_ar and song.lyrics_ar.strip():
        return
    song_service.update_song(
        session, song.id,
        lyrics_ar=SONG_LYRICS_AR,
        purpose=SONG_PURPOSE,
        duration_seconds=SONG_DURATION_SECONDS,
        production_notes=SONG_PRODUCTION_NOTES,
        suno_style_prompt=SONG_SUNO_STYLE_PROMPT,
    )
    if not episode.includes_song:
        EpisodeService().update_episode(session, episode.id, includes_song=True)


def _populate_shorts(session: Session, episode: Episode) -> None:
    scene_service = SceneService()
    scenes_by_index = {s.order_index: s for s in scene_service.list_episode_scenes(session, episode.id)}
    for short in ShortService().list_episode_shorts(session, episode.id):
        entry = SHORTS.get(short.short_index)
        if entry is None or (short.title_ar and short.title_ar.strip()):
            continue  # unknown index, or already populated/human-edited — never overwrite
        ShortService().update_short(session, short.id, **entry["fields"])
        scene_ids = [
            scenes_by_index[i].id for i in entry["source_scene_order_indexes"] if i in scenes_by_index
        ]
        if scene_ids:
            ShortService().link_source_scenes(session, short.id, scene_ids)


def _populate_seo(session: Session, episode: Episode) -> None:
    if episode.description_ar and episode.description_ar.strip():
        return
    EpisodeService().update_episode(
        session, episode.id,
        description_ar=SEO_DESCRIPTION_AR,
        description_en=SEO_DESCRIPTION_EN,
        hashtags=SEO_HASHTAGS,
        credits_text=SEO_CREDITS_TEXT,
    )


def _populate_thumbnail_concept(session: Session, episode: Episode) -> None:
    existing = (
        session.query(PromptTemplate)
        .filter_by(name=_THUMBNAIL_TEMPLATE_NAME, episode_id=episode.id)
        .one_or_none()
    )
    if existing is not None:
        return
    PromptTemplateService().create_prompt_template(
        session,
        name=_THUMBNAIL_TEMPLATE_NAME,
        category=PromptCategory.THUMBNAIL,
        prompt_type=PromptType.IMAGE,
        text_en=THUMBNAIL_CONCEPT_TEXT,
        is_reusable=False,
        episode_id=episode.id,
    )


def populate_episode_001_production_content(session: Session) -> Episode:
    """Idempotently fill Episode 001 with real production content.

    Safe to call any number of times, including against a database where
    a human has already edited some of this content through the GUI —
    every section below only ever writes into a field that is currently
    empty. Commits on success, matching :func:`app.core.db.seed.seed_demo_data`'s
    own contract (this always calls it first to guarantee Melissa,
    Bilsan, Episode 001, and its 3 Shorts exist).
    """
    seeded = seed_demo_data(session)
    episode: Episode = seeded["episode_001"]
    melissa: Character = seeded["melissa"]
    bilsan: Character = seeded["bilsan"]
    tortor = _get_or_create_tortor(session)

    featured_ids = {c.id for c in episode.characters_featured}
    if tortor.id not in featured_ids:
        episode.characters_featured.append(tortor)
        session.flush()

    _populate_script(session, episode)
    _populate_scenes(session, episode, melissa, bilsan, tortor)
    _populate_song(session, episode)
    _populate_shorts(session, episode)
    _populate_seo(session, episode)
    _populate_thumbnail_concept(session, episode)

    session.commit()
    logger.info(
        "Episode 001 production content ready: %d scene(s), %d short(s).",
        len(episode.scenes), len(episode.shorts),
    )
    return episode
