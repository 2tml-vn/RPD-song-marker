async def identify_song(shazam, shazam_en, audio_path, current_sec, gap, snippets_dir):
    """
    Attempts to identify a song using temporary files.
    Tries Shazam first, then falls back to Local Memory.
    """
    found_name = None
    sliding_windows = shared_utils.get_optimal_sliding_windows(gap)

    for offset, d in sliding_windows:
        logger.debug(f"  Attempt {sliding_windows.index((offset, d)) + 1}/{len(sliding_windows)}: offset +{offset}s, duration {d}s...")
        
        # Optimized Robust Pass
        passes = [
            ("Robust", ["highpass=f=100,equalizer=f=3000:t=q:w=1:g=6,loudnorm=I=-16:TP=-1.5:LRA=11"])
        ]

        for pass_name, filters in passes:
            temp_name = snippets_dir / f"seg_{int(time.time())}_{pass_name}.wav"
            cmd = [
                "ffmpeg", "-y", "-ss", str(current_sec + offset), "-t", str(d), "-i", str(audio_path),
                "-vn", "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
                "-af", ",".join(filters),
                "-f", "wav", "-loglevel", "error", str(temp_name)
            ]
            
            try:
                subprocess.run(cmd, check=True)
                if not temp_name.exists() or temp_name.stat().st_size < 1000:
                    continue

                async def recognize_with_retry(client, file_path):
                    try:
                        # Use modern recognize method with file path
                        return await asyncio.wait_for(client.recognize(file_path), timeout=15)
                    except:
                        return None

                logger.debug(f"  [{pass_name} Pass] Trying Shazam...")
                out = await recognize_with_retry(shazam, str(temp_name))
                if not (out and 'track' in out):
                    out = await recognize_with_retry(shazam_en, str(temp_name))

                # 1. SHAZAM MATCH
                if out and 'track' in out:
                    track = out['track']
                    original_title = track['title']
                    artist = track['subtitle']
                    track_id = track.get('key')

                    if artist.lower() in ["moonbooter", "generic artist"]:
                        logger.debug(f"  Discarding suspected false positive: {original_title} - {artist}")
                        continue

                    title = clean_title(original_title)
                    en_name = None

                    if track_id:
                        try:
                            en_data = await shazam_en.track_about(int(track_id))
                            en_track = Serialize.track(data=en_data)
                            if en_track.title:
                                cleaned_shazam_en = clean_title(en_track.title)
                                if cleaned_shazam_en.lower() != title.lower():
                                    en_name = cleaned_shazam_en
                        except: pass

                    if title in JAPANESE_TO_ENGLISH_MAP:
                        en_name = JAPANESE_TO_ENGLISH_MAP[title]

                    if en_name:
                        title = f"{title} ({en_name})"

                    found_name = f"{title} - {artist}"
                    logger.info(f"  [MATCH] {found_name}")
                    break

                # 2. LOCAL MEMORY FALLBACK
                else:
                    logger.debug(f"  [{pass_name} Pass] Shazam: No match. Checking Local Memory...")
                    try:
                        sr_in, data_in = wav.read(str(temp_name))
                        y_in = data_in.astype(np.float32) / 32768.0
                        fp_in = compute_fingerprint(y_in, sr_in)
                        local_name, score = dna_matcher.find_match(fp_in)
                        if local_name:
                            logger.info(f"  [LOCAL MATCH] {local_name} (Similarity: {score:.3f})")
                            found_name = local_name
                            break
                    except Exception as local_err:
                        logger.debug(f"    Local check failed: {local_err}")
                    
                    logger.debug(f"  [{pass_name} Pass] No match.")

            except Exception as e:
                logger.error(f"  Pass {pass_name} failed: {e}")
            finally:
                if temp_name.exists(): temp_name.unlink()
            
            if found_name: break
        if found_name: break
    
    return found_name if found_name else "Unidentified"
