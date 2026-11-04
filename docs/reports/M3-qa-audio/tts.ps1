param([string]$In, [string]$Out, [int]$Rate = 0)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Irina Desktop')
$s.Rate = $Rate
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($Out, $fmt)
$s.Speak([IO.File]::ReadAllText($In, [Text.Encoding]::UTF8))
$s.Dispose()
