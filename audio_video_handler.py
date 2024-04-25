import os
import audio_extraction
import audio_translation
import inference

CHECKPOINT_PATH = "/content/Wav2Lip/checkpoints/wav2lip_gan.pth" 
FINAL_OUTPUT_DIRECTOR = "/content/output.mp4"
OUTPUT_TRANSLATED_AUDIO_LOCATION = "/content/translated.wav"
OUTPUT_AUDIO_FILE_LOCATION="/content"
DEFAULT_VIDEO_FILE ="/sample_data/uploaded.mp4"
DEFAULT_VIDEO_FILE_NAME ="video"
DEFAULT_LANGAUGE = "English"
DEFAULT_IMAGE_FILE= "/sample_data/uploaded.jpg"


def convert_video(language,video_file=DEFAULT_VIDEO_FILE, output_audio_file_location=OUTPUT_AUDIO_FILE_LOCATION, output_translated_audio_location=OUTPUT_TRANSLATED_AUDIO_LOCATION, video_file_name=DEFAULT_VIDEO_FILE_NAME , final_output_directory=FINAL_OUTPUT_DIRECTOR):
    try:
        print("started converting")
        print(language)
        video_file_name = "extracted_audio"
        print(video_file_name)
        audio_file_id = "/" + video_file_name +".wav"
        output_audio_file_location = output_audio_file_location + audio_file_id
        print(output_audio_file_location)
        audio_extraction.extract_audio(video_file, output_audio_file_location)
        print("audio extracted")
        transation_completed =audio_translation.translate_voice(language,output_audio_file_location,
                                                                              output_translated_audio_location
                                                                              )
        print("translation completed")

        if transation_completed:

            try:
                conversion_completed=inference.convert(output_translated_audio_location, video_file, CHECKPOINT_PATH, final_output_directory)
                if conversion_completed:
                    return True
            except Exception as e:
                print(e)
        else:
            return False   


    except Exception as e:
        print("Exception has occured ...  convert_video() ")
        print(e)
        return False
