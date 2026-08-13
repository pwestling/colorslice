from fasthtml.common import serve

from colorslice.app import app as colorslice_app


# Keep the ASGI entrypoint explicit for Vercel's Python runtime scanner.
app = colorslice_app


if __name__ == "__main__":
    serve()
