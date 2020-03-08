"""Methods for generating ASR artifacts."""
import logging
import re
import shutil
import subprocess
import tempfile
import typing
from pathlib import Path

import rhasspynlu

PronunciationsType = typing.Dict[str, typing.List[typing.List[str]]]

_DIR = Path(__file__).parent
_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------


class MissingWordPronunciationsException(Exception):
    """Raised when missing word pronunciations and no g2p model."""

    def __init__(self, words: typing.List[str]):
        super().__init__(self)
        self.words = words

    def __str__(self):
        return f"Missing pronunciations for: {self.words}"


# -------------------------------------------------------------------


def train(
    graph_dict: typing.Dict[str, typing.Any],
    dictionary_path: Path,
    language_model_path: Path,
    pronunciations: PronunciationsType,
    dictionary_word_transform: typing.Optional[typing.Callable[[str], str]] = None,
    g2p_model: typing.Optional[Path] = None,
    g2p_word_transform: typing.Optional[typing.Callable[[str], str]] = None,
    missing_words_path: typing.Optional[Path] = None,
    balance_counts: bool = True,
):
    """Re-generates language model and dictionary from intent graph"""
    g2p_word_transform = g2p_word_transform or (lambda s: s)

    # Convert to directed graph
    graph = rhasspynlu.json_to_graph(graph_dict)

    # Generate counts
    intent_counts = rhasspynlu.get_intent_ngram_counts(
        graph, balance_counts=balance_counts
    )

    # Use mitlm to create language model
    vocabulary: typing.Set[str] = set()

    with tempfile.NamedTemporaryFile(mode="w") as lm_file:

        # Create ngram counts file
        count_file = open(str(language_model) + ".counts", "w")
        with count_file:
            for intent_name in intent_counts:
                for ngram, count in intent_counts[intent_name].items():
                    if dictionary_word_transform:
                        ngram = [dictionary_word_transform(w) for w in ngram]

                    # word [word] ... <TAB> count
                    print(*ngram, file=count_file, end="")
                    print("\t", count, file=count_file)

            count_file.seek(0)
            with tempfile.NamedTemporaryFile(mode="w+") as vocab_file:
                estimate_ngram = shutil.which("estimate-ngram") or (
                    _DIR / "estimate-ngram"
                )
                ngram_command = [
                    str(estimate_ngram),
                    "-order",
                    "3",
                    "-counts",
                    count_file.name,
                    "-write-lm",
                    lm_file.name,
                    "-write-vocab",
                    vocab_file.name,
                ]

                _LOGGER.debug(ngram_command)
                subprocess.check_call(ngram_command)

                # Extract vocabulary
                vocab_file.seek(0)
                for line in vocab_file:
                    line = line.strip()
                    if not line.startswith("<"):
                        vocabulary.add(line)

        assert vocabulary, "No words in vocabulary"

        # Write dictionary
        with tempfile.NamedTemporaryFile(mode="w") as dict_file:

            # Look up words
            missing_words: typing.Set[str] = set()

            # Look up each word
            for word in vocabulary:
                word_phonemes = pronunciations.get(word)
                if not word_phonemes:
                    # Add to missing word list
                    _LOGGER.warning("Missing word '%s'", word)
                    missing_words.add(word)
                    continue

                # Write CMU format
                for i, phonemes in enumerate(word_phonemes):
                    phoneme_str = " ".join(phonemes).strip()
                    if i == 0:
                        # word
                        print(word, phoneme_str, file=dict_file)
                    else:
                        # word(n)
                        print(f"{word}({i+1})", phoneme_str, file=dict_file)

            # Open missing words file
            missing_file: typing.Optional[typing.TextIO] = None
            if missing_words_path:
                missing_file = open(missing_words_path, "w")

            if missing_words:
                # Fail if no g2p model is available
                if not g2p_model:
                    raise MissingWordPronunciationsException(list(missing_words))

                # Guess word pronunciations
                _LOGGER.debug("Guessing pronunciations for %s", missing_words)
                guesses = guess_pronunciations(
                    missing_words,
                    g2p_model,
                    g2p_word_transform=g2p_word_transform,
                    num_guesses=1,
                )

                # Output is a pronunciation dictionary.
                # Append to existing dictionary file.
                for guess_word, guess_phonemes in guesses:
                    guess_phoneme_str = " ".join(guess_phonemes).strip()
                    print(guess_word, guess_phoneme_str, file=dict_file)

                    if missing_file:
                        print(guess_word, guess_phoneme_str, file=missing_file)

            # Close missing words file
            if missing_file:
                _LOGGER.debug("Wrote missing words to %s", str(missing_words_path))
                missing_file.close()

            # -----------------------------------------------------

            # Copy dictionary
            dict_file.seek(0)
            shutil.copy(dict_file.name, dictionary_path)
            _LOGGER.debug("Wrote dictionary to %s", str(dictionary_path))

        # -------------------------------------------------------------

        # Copy language model
        lm_file.seek(0)
        shutil.copy(lm_file.name, language_model_path)
        _LOGGER.debug("Wrote language model to %s", str(language_model_path))


# -----------------------------------------------------------------------------


def guess_pronunciations(
    words: typing.Iterable[str],
    g2p_model: Path,
    g2p_word_transform: typing.Optional[typing.Callable[[str], str]] = None,
    num_guesses: int = 1,
) -> typing.Iterable[typing.Tuple[str, typing.List[str]]]:
    """Guess phonetic pronunciations for words. Yields (word, phonemes) pairs."""
    g2p_word_transform = g2p_word_transform or (lambda s: s)

    with tempfile.NamedTemporaryFile(mode="w") as wordlist_file:
        for word in words:
            word = g2p_word_transform(word)
            print(word, file=wordlist_file)

        wordlist_file.seek(0)
        phonetisaurus_apply = shutil.which("phonetisaurus-apply") or (
            _DIR / "phonetisaurus-apply"
        )
        g2p_command = [
            str(phonetisaurus_apply),
            "--model",
            str(g2p_model),
            "--word_list",
            wordlist_file.name,
            "--nbest",
            str(num_guesses),
        ]

        _LOGGER.debug(g2p_command)
        g2p_lines = subprocess.check_output(
            g2p_command, universal_newlines=True
        ).splitlines()

        # Output is a pronunciation dictionary.
        # Append to existing dictionary file.
        for line in g2p_lines:
            line = line.strip()
            if line:
                word, *phonemes = line.split()
                yield (word.strip(), phonemes)


# -----------------------------------------------------------------------------


def read_dict(
    dict_file: typing.Iterable[str],
    word_dict: typing.Optional[PronunciationsType] = None,
) -> PronunciationsType:
    """Loads a CMU pronunciation dictionary."""
    if word_dict is None:
        word_dict = {}

    for i, line in enumerate(dict_file):
        line = line.strip()
        if not line:
            continue

        try:
            # Use explicit whitespace (avoid 0xA0)
            word, *pronounce = re.split(r"[ \t]+", line)

            word = word.split("(")[0]

            if word in word_dict:
                word_dict[word].append(pronounce)
            else:
                word_dict[word] = [pronounce]
        except Exception as e:
            _LOGGER.warning("read_dict: %s (line %s)", e, i + 1)

    return word_dict
