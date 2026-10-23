package io.github.bj0322.poschat

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import com.chaquo.python.Python
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * PO노트 녹음: 화면이 꺼지거나 다른 앱으로 가도 강의를 계속 받아 적도록 포그라운드 서비스에서 마이크를 연다.
 * 16kHz 모노 PCM16을 0.1초(1600샘플)씩 읽어 Python android_main.mic_block(bytes)로 넘긴다.
 * 시작·중지는 android_main의 sounddevice 대신 객체가 Host.micStart/micStop으로 부른다.
 */
class RecordingService : Service() {
    @Volatile private var running = false
    private var thread: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP_NOTE) {
            // 알림의 '녹음 중지': 화면에서 누른 것과 같이 노트를 마무리한다(Python이 micStop으로 서비스를 멈춘다)
            Thread { runCatching { python().callAttr("call", "po_stop", "[]") } }.start()
            return START_NOT_STICKY
        }
        if (running) {
            finishStart(null)
            return START_NOT_STICKY
        }
        val notification = notification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {  // 마이크 종류(microphone)는 Android 11부터
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else startForeground(NOTIFICATION_ID, notification)
        val record = try {
            openRecorder()
        } catch (e: Exception) {
            finishStart("마이크를 열지 못했습니다: ${e.message ?: e}")
            stopSelf()
            return START_NOT_STICKY
        }
        wakeLock = (getSystemService(Context.POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "poschat:po-note").apply { acquire(6 * 3600 * 1000L) }
        running = true
        thread = Thread({ readLoop(record) }, "po-note-mic").apply { start() }
        finishStart(null)
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        running = false
        thread?.join(2000)
        thread = null
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        finishStart("녹음 서비스가 멈췄습니다.")  // 시작을 기다리던 쪽이 있으면 풀어 준다
        super.onDestroy()
    }

    @SuppressLint("MissingPermission")  // Host.micStart가 마이크 권한을 확인한 뒤에만 서비스를 시작한다
    private fun openRecorder(): AudioRecord {
        val minBuffer = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (minBuffer <= 0) throw IllegalStateException("이 기기는 16kHz 녹음을 지원하지 않습니다($minBuffer)")
        val buffer = maxOf(minBuffer, BLOCK * 2 * 4)
        // 음성 인식용 입력(VOICE_RECOGNITION)은 통화용 잡음 제거·자동 음량을 끈 소리를 준다. 없는 기기는 일반 마이크.
        for (source in intArrayOf(MediaRecorder.AudioSource.VOICE_RECOGNITION, MediaRecorder.AudioSource.MIC)) {
            val record = try {
                AudioRecord(source, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, buffer)
            } catch (e: Exception) {
                Log.w("Poschat", "AudioRecord($source) 실패", e)
                continue
            }
            if (record.state == AudioRecord.STATE_INITIALIZED) {
                record.startRecording()
                if (record.recordingState == AudioRecord.RECORDSTATE_RECORDING) return record
            }
            record.release()
        }
        throw IllegalStateException("마이크를 쓸 수 없습니다(다른 앱이 쓰고 있거나 권한이 없습니다)")
    }

    private fun readLoop(record: AudioRecord) {
        val bytes = ByteArray(BLOCK * 2)
        try {
            val module = python()
            while (running) {
                var filled = 0
                while (running && filled < bytes.size) {
                    val n = record.read(bytes, filled, bytes.size - filled)
                    if (n < 0) throw IllegalStateException("녹음이 끊겼습니다(AudioRecord $n)")
                    filled += n
                }
                if (filled == bytes.size) module.callAttr("mic_block", bytes)
            }
        } catch (e: Exception) {
            Log.e("Poschat", "녹음 오류", e)
            runCatching { python().callAttr("mic_error", e.message ?: e.toString()) }
        } finally {
            runCatching { record.stop() }
            record.release()
        }
    }

    private fun python(): com.chaquo.python.PyObject = Python.getInstance().getModule("android_main")

    private fun notification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "PO노트 녹음", NotificationManager.IMPORTANCE_LOW)
                    .apply { description = "강의를 녹음해 받아 적는 동안 표시됩니다" },
            )
        }
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, RecordingService::class.java).setAction(ACTION_STOP_NOTE),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        @Suppress("DEPRECATION")
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) Notification.Builder(this, CHANNEL)
        else Notification.Builder(this)
        return builder.setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("PO노트 녹음 중")
            .setContentText("강의를 받아 적고 있습니다")
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "녹음 중지", stop).build())
            .build()
    }

    companion object {
        const val SAMPLE_RATE = 16000
        const val BLOCK = 1600
        private const val CHANNEL = "po_note_recording"
        private const val NOTIFICATION_ID = 1601
        private const val ACTION_STOP_NOTE = "io.github.bj0322.poschat.STOP_NOTE"

        @Volatile private var startLatch: CountDownLatch? = null
        @Volatile private var startError: String? = null

        private fun finishStart(error: String?) {
            val latch = startLatch ?: return
            startLatch = null
            startError = error
            latch.countDown()
        }

        /** 서비스를 시작하고 마이크가 열릴 때까지 기다린다. 실패하면 이유, 성공하면 null. */
        fun start(context: Context): String? {
            val latch = CountDownLatch(1)
            startError = null
            startLatch = latch
            val intent = Intent(context, RecordingService::class.java)
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent)
                else context.startService(intent)
            } catch (e: Exception) {  // 앱이 화면에 없을 때(ForegroundServiceStartNotAllowedException) 등
                startLatch = null
                return "녹음 서비스를 시작하지 못했습니다: ${e.message ?: e}"
            }
            if (!latch.await(10, TimeUnit.SECONDS)) {
                startLatch = null
                return "마이크가 열리지 않았습니다. 다시 시도하세요."
            }
            return startError
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, RecordingService::class.java))
        }
    }
}
