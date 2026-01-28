def format_song_entry(song_info):
    if not song_info: return ""

    # Custom Mappings (Expandable)
    # Format: "original name": "replacement name"
    mappings = {
        "nightcord - deaya": "キャットラビング - 25時、ナイトコードで。",
        "deaya - nightcord": "キャットラビング - 25時、ナイトコードで。",
        "Humancity - t'Awi": "極楽浄土",
        "Day Dreamer - Ashraf Hamzi": "無理すぎオタクハート",
        "Bend - Ultrademon": "えれくとりっく・えんじぇぅ (Electric Angel)"
    }

    # English translations for Japanese songs
    english_translations = {
        "キャットラビング": "Cat Loving",
        "極楽浄土": "Gokuraku Jodo (Paradise)",
        "無理すぎオタクハート": "Otaku Heart is Too Much",
        "えれくとりっく・えんじぇぅ": "Electric Ange"
    }

    # Artist translations
    artist_translations = {
        "25時、ナイトコードで。": "25th Nightcord",
        "t'Awi": "t'Awi",
        "Ashraf Hamzi": "Ashraf Hamzi",
        "Ultrademon": "Ultrademon",
        "deaya": "deaya"
    }

    # Check for exact or normalized match
    normalized = song_info.strip().lower()
    if normalized in mappings:
        song_info = mappings[normalized]

    if ' - ' in song_info:
        parts = song_info.split(' - ', 1)
        # parts[0] is title, parts[1] is artist
        title = re.sub(r'\s*(\([^)]*\)|\[[^\]]*\])$', '', parts[0].strip())
        artist = parts[1].strip().replace('.', '')

        # If artist name is absurdly long (e.g. huge cast lists), keep only title
        if len(artist) > 60:
            # Check if we have an English translation for the title
            english_title = english_translations.get(title, "")
            if english_title:
                return f"{title} ({english_title})"
            else:
                return title

        # Check if we have an English translation for the title and artist
        english_title = english_translations.get(title, "")
        english_artist = artist_translations.get(artist, "")

        if english_title and english_artist:
            # Format as: [original title] ([english title]) - [original artist] ([english artist])
            return f"{title} ({english_title}) - {artist} ({english_artist})"
        elif english_title:
            # Format as: [original title] ([english title]) - [original artist]
            return f"{title} ({english_title}) - {artist}"
        elif english_artist:
            # Format as: [original title] - [original artist] ([english artist])
            return f"{title} - {artist} ({english_artist})"
        else:
            return f"{title} - {artist}"
    else:
        # If no artist, just check for English translation
        english_title = english_translations.get(song_info.strip(), "")
        if english_title:
            return f"{song_info.strip()} ({english_title})"
        else:
            return song_info.strip().replace('.', '')