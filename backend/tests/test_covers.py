"""Tests for backend/covers.py.

The catalogues this app reads are bibliographic: the DNB and K10plus return
MARC and Dublin Core with no image in them, so a cover has always been a guess
at a URL on a separate service. Measured across ten ISBNs, a URL was offered
for 10 and only 8 resolved to an image; the other two were stored anyway, so
those books showed a broken cover for good.

The behaviour worth pinning hardest is the three-way answer. A 404 means the
service has no cover and the next candidate is worth trying. A 503 means
nothing is known, and Open Library really did return one twice in a row for a
book it very likely has, so discarding a cover on that would lose it to a blip.
"""

import httpx
import pytest
import respx

import covers

OPEN_LIBRARY = "https://covers.openlibrary.org/"
DNB = "https://portal.dnb.de/opac/mvb/cover"

GERMAN = "9783423280150"
ENGLISH = "9780441013593"


def image(status: int = 200) -> httpx.Response:
    return httpx.Response(
        status, content=b"\xff\xd8\xff\xe0jpegbytes", headers={"content-type": "image/jpeg"}
    )


class TestOrder:
    def test_a_german_isbn_asks_the_dnb_first(self):
        """The book trade's own service is the one that has them."""
        assert covers.candidates(GERMAN)[0].startswith(DNB)

    def test_anything_else_asks_open_library_first(self):
        assert covers.candidates(ENGLISH)[0].startswith(OPEN_LIBRARY)

    def test_default_false_is_kept_on_the_open_library_url(self):
        """Without it every request answers with a grey placeholder image.

        A book with no cover then gets one that looks broken rather than no
        cover at all, and nothing downstream can tell the difference.
        """
        assert "default=false" in covers.open_library_url(ENGLISH)


class TestChecking:
    @pytest.mark.asyncio
    async def test_a_verified_cover_is_returned(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())
            assert await covers.resolve(ENGLISH) == covers.open_library_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_a_404_moves_on_to_the_next_service(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=httpx.Response(404))
            mock.get(url__startswith=DNB).mock(return_value=image())

            assert await covers.resolve(ENGLISH) == covers.dnb_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_no_service_having_it_is_no_cover(self):
        """Better than a link that renders as a broken image for good."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__regex=r".*").mock(return_value=httpx.Response(404))
            assert await covers.resolve(ENGLISH) is None

    @pytest.mark.asyncio
    async def test_a_200_that_is_not_an_image_is_refused(self):
        """An error page served with the wrong status is the other failure."""
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__regex=r".*").mock(
                return_value=httpx.Response(200, text="<html>not found</html>")
            )
            assert await covers.resolve(ENGLISH) is None


class TestTransientFailures:
    """A 503 is not a 404, and treating it as one loses covers to a blip."""

    @pytest.mark.asyncio
    async def test_a_5xx_keeps_the_url_rather_than_discarding_it(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=httpx.Response(503))
            mock.get(url__startswith=DNB).mock(return_value=httpx.Response(404))

            assert await covers.resolve(ENGLISH) == covers.open_library_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_a_timeout_keeps_the_url_too(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(
                side_effect=httpx.ConnectTimeout("slow")
            )
            mock.get(url__startswith=DNB).mock(return_value=httpx.Response(404))

            assert await covers.resolve(ENGLISH) == covers.open_library_url(ENGLISH)

    @pytest.mark.asyncio
    async def test_a_verified_cover_beats_an_unverifiable_one(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=httpx.Response(503))
            mock.get(url__startswith=DNB).mock(return_value=image())

            assert await covers.resolve(ENGLISH) == covers.dnb_url(ENGLISH)


class TestASuppliedUrl:
    """A URL from a volume record is not a guess: it exists by construction."""

    SUPPLIED = "https://books.google.com/thumb.jpg"

    @pytest.mark.asyncio
    async def test_it_is_tried_first_and_kept(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(self.SUPPLIED).mock(return_value=image())
            mock.get(url__regex=r".*").mock(return_value=image())

            assert await covers.resolve(ENGLISH, self.SUPPLIED) == self.SUPPLIED

    @pytest.mark.asyncio
    async def test_a_dead_supplied_url_falls_through(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(self.SUPPLIED).mock(return_value=httpx.Response(404))
            mock.get(url__startswith=OPEN_LIBRARY).mock(return_value=image())

            assert await covers.resolve(ENGLISH, self.SUPPLIED) == covers.open_library_url(
                ENGLISH
            )


class TestBadInput:
    @pytest.mark.asyncio
    async def test_a_string_that_is_not_an_isbn_costs_no_request(self):
        with respx.mock(assert_all_called=False) as mock:
            any_call = mock.get(url__regex=r".*").mock(return_value=image())
            assert await covers.resolve("not-an-isbn") is None
            assert not any_call.called

    @pytest.mark.asyncio
    async def test_a_supplied_url_survives_an_unparseable_isbn(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__regex=r".*").mock(return_value=image())
            assert await covers.resolve("nonsense", "https://x/y.jpg") == "https://x/y.jpg"
