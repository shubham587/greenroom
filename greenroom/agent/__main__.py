"""LiveKit worker entrypoint. Registers with LiveKit and waits to be assigned a room.

Serves no HTTP and needs no ingress - it dials out.
"""

from greenroom.adapters.voice import main

if __name__ == "__main__":
    main()
