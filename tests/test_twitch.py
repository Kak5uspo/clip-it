"""Helpers around TwitchDownloaderCLI that can be checked without the network."""
import pytest

from clipforge.twitch import vod_id


@pytest.mark.parametrize(
    "reference",
    [
        "2924976553",
        "https://www.twitch.tv/videos/2924976553",
        "https://www.twitch.tv/videos/2924976553?t=4h30m0s",
        "twitch.tv/videos/2924976553/",
    ],
)
def test_vod_id_is_taken_from_an_id_or_a_link(reference):
    assert vod_id(reference) == "2924976553"


def test_something_that_is_not_a_vod_is_rejected():
    with pytest.raises(ValueError, match="clips"):
        vod_id("https://www.twitch.tv/somechannel/clips")
