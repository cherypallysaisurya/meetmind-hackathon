from app.detect.rules import RulesDetector, is_handoff, looks_like_question, says_name, with_real_name

ALIASES = ["Surya", "Sur", "Suria"]   # the eval user's list, with the spelling whisper usually produces
TOPICS = ["retrieval", "evaluation", "data pipelines"]


def detector():
    return RulesDetector(ALIASES, TOPICS, attention_window_s=15, after_you_spoke_window_s=10)


def test_name_match_is_fuzzy_but_not_loose():
    assert says_name("Suria, what batch size did you use?", ALIASES)      # whisper's spelling
    assert says_name("Thanks, Siraia. How about you?", ALIASES)           # heard in the eval
    assert says_name("Sereya, how long will the rework take?", ALIASES)   # heard in the eval
    assert says_name("sur what do you think", ALIASES)
    assert not says_name("Sarah, what do you think?", ALIASES)
    assert not says_name("sure, let's do that", ALIASES)                  # "sure" must not match "Sur"
    assert not says_name("Surely we can ship on Friday?", ALIASES)        # a real word, 0.73 similar to Surya
    assert not says_name("So, how does the pipeline work?", ALIASES)      # "So" is what the STT made of "Sur"


def test_question_cues():
    assert looks_like_question("What batch size did you use")
    assert looks_like_question("Surya, what batch size did you use")
    assert looks_like_question("the index rebuild takes twelve minutes, right?")
    assert looks_like_question("Any thoughts on the deployment plan")
    assert not looks_like_question("Yesterday I finished the data pipeline.")


def test_name_alone_fires_and_a_question_to_someone_else_does_not():
    assert detector().evaluate("Surya did a great job on that", now_s=10, you_spoke_at_s=None, attention_at_s=None).fires
    quiet = detector().evaluate("Alex, what batch size did you use?", now_s=10, you_spoke_at_s=None, attention_at_s=None)
    assert not quiet.fires
    assert quiet.reasons == ["question"]


def test_attention_fires_inside_its_window_only():
    assert detector().evaluate("so what do we do next", now_s=20, you_spoke_at_s=None, attention_at_s=10).fires
    assert not detector().evaluate("so what do we do next", now_s=40, you_spoke_at_s=None, attention_at_s=10).fires


def test_you_question_right_after_the_user_spoke_fires():
    candidate = detector().evaluate("and what would you suggest?", now_s=30, you_spoke_at_s=25, attention_at_s=None)
    assert candidate.fires
    assert candidate.reasons == ["question", "after you spoke"]
    assert not detector().evaluate("and what would you suggest?", now_s=60, you_spoke_at_s=25, attention_at_s=None).fires
    assert not detector().evaluate("thank you", now_s=30, you_spoke_at_s=25, attention_at_s=None).fires


def test_topic_question_after_the_user_spoke_fires_but_topic_alone_is_only_weak():
    fires = detector().evaluate("how long does the retrieval index take now?", now_s=30, you_spoke_at_s=25, attention_at_s=None)
    assert fires.fires and "your topic" in fires.reasons
    weak = detector().evaluate("how long does the retrieval index take now?", now_s=30, you_spoke_at_s=None, attention_at_s=None)
    assert not weak.fires and weak.weak and weak.score == 0.5


def test_topic_words_match_by_word():
    weak = detector().evaluate("So, how does the pipeline handle long documents?", now_s=30, you_spoke_at_s=None, attention_at_s=None)
    assert weak.weak and weak.reasons == ["question", "your topic"]


def test_a_plain_question_right_after_the_user_spoke_is_weak_not_fired():
    weak = detector().evaluate("And what would the bigger index cost us per month?", now_s=30, you_spoke_at_s=27, attention_at_s=None)
    assert weak.weak and weak.reasons == ["question", "follows your turn"]
    quiet = detector().evaluate("And what would the bigger index cost us per month?", now_s=60, you_spoke_at_s=27, attention_at_s=None)
    assert not quiet.weak and not quiet.fires


def test_small_talk_stays_quiet():
    for text in ("how are you doing today", "good morning everyone", "thanks everyone, that's all from my side"):
        assert not detector().evaluate(text, now_s=10, you_spoke_at_s=None, attention_at_s=None).fires


def test_the_misheard_name_is_replaced_by_the_real_one():
    assert with_real_name("Saria, what batch size did you use?", ["Surya", "Sur", "Suria"], "Surya") == "Surya, what batch size did you use?"
    assert with_real_name("sur, your take?", ALIASES, "Surya") == "Surya, your take?"
    assert with_real_name("Surya, your take?", ALIASES, "Surya") == "Surya, your take?"
    assert with_real_name("Alex, your take?", ALIASES, "Surya") == "Alex, your take?"


def test_a_handoff_passes_a_question_on_but_a_question_about_taking_something_is_not_one():
    assert is_handoff("Surya, do you want to take that one?")
    assert is_handoff("That one is for you as well, Surya.")
    assert is_handoff("Over to you, Sur.")
    assert not is_handoff("Surya, do you want to take the lead on PDF support?")
    assert not is_handoff("What batch size did you end up using?")


def test_one_on_one_treats_every_question_as_mine():
    rules = detector()
    question = "What would happen if we used bigger chunks?"
    assert not rules.evaluate(question, now_s=10, you_spoke_at_s=None, attention_at_s=None).fires
    rules.one_on_one = True
    candidate = rules.evaluate(question, now_s=10, you_spoke_at_s=None, attention_at_s=None)
    assert candidate.fires and "one-on-one" in candidate.reasons
    assert not rules.evaluate("That went well.", now_s=10, you_spoke_at_s=None, attention_at_s=None).fires



def test_a_tag_question_counts_even_when_speech_to_text_ends_it_with_a_period():
    assert looks_like_question("I don't think you're actually calling the API. Right. You're just querying the database directly.")
    assert looks_like_question("We're going to deduplicate on ingestion, right. Like I think for this demo")
    assert looks_like_question("You have your repo somewhere else, right?")
    assert not looks_like_question("Right, so each repo could have issues and tasks associated with them.")


def test_a_long_question_right_after_you_spoke_still_counts_from_its_start():
    rules = detector()
    late = rules.evaluate("Why did you pick recall at ten rather than mean reciprocal rank?", now_s=22.0, you_spoke_at_s=10.0, attention_at_s=None)
    assert not late.fires, "measured at its end, the sentence is 12 s after the user spoke"
    on_time = rules.evaluate("Why did you pick recall at ten rather than mean reciprocal rank?", now_s=22.0, you_spoke_at_s=10.0, attention_at_s=None, started_s=18.0)
    assert on_time.fires and "after you spoke" in on_time.reasons   # the sentence says "you", so the stronger reason applies
