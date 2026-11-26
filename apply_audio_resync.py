
from pathlib import Path

ROOT = Path("src/apps/mplayerc")
files = {}


def load(name):
    if name not in files:
        path = ROOT / name
        raw = path.read_bytes()

        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding = "utf-16-le" if raw.startswith(b"\xff\xfe") else "utf-16-be"
        else:
            encoding = "latin-1"

        text = raw.decode(encoding)
        newline = "\r\n" if "\r\n" in text else "\n"

        files[name] = [
            path,
            text.replace("\r\n", "\n"),
            encoding,
            newline,
        ]

    return files[name]


def replace(name, old, new):
    entry = load(name)
    count = entry[1].count(old)

    if count != 1:
        raise RuntimeError(
            f"{name}: expected exactly one match, found {count}:\n{old}"
        )

    entry[1] = entry[1].replace(old, new, 1)


# ============================================================
# AppSettings.h
# ============================================================

replace(
    "AppSettings.h",
    "\tbool\t\t\tfFastSeek;",
    """\tbool\t\t\tfFastSeek;
\tbool\t\t\tbAutoAVResync;
\tint\t\t\tnAutoAVResyncMinutes;"""
)


# ============================================================
# AppSettings.cpp
# ============================================================

replace(
    "AppSettings.cpp",
    "\tfFastSeek = true;",
    """\tfFastSeek = true;
\tbAutoAVResync = false;
\tnAutoAVResyncMinutes = 15;"""
)

replace(
    "AppSettings.cpp",
    "\tprofile.ReadBool(IDS_R_SETTINGS, IDS_RS_FASTSEEK_KEYFRAME, fFastSeek);",
    """\tprofile.ReadBool(IDS_R_SETTINGS, IDS_RS_FASTSEEK_KEYFRAME, fFastSeek);
\tprofile.ReadBool(IDS_R_SETTINGS, L"AutoAVResync", bAutoAVResync);
\tprofile.ReadInt(IDS_R_SETTINGS, L"AutoAVResyncMinutes", nAutoAVResyncMinutes, 1, 120);"""
)

replace(
    "AppSettings.cpp",
    "\tprofile.WriteBool(IDS_R_SETTINGS, IDS_RS_FASTSEEK_KEYFRAME, fFastSeek);",
    """\tprofile.WriteBool(IDS_R_SETTINGS, IDS_RS_FASTSEEK_KEYFRAME, fFastSeek);
\tprofile.WriteBool(IDS_R_SETTINGS, L"AutoAVResync", bAutoAVResync);
\tprofile.WriteInt(IDS_R_SETTINGS, L"AutoAVResyncMinutes", nAutoAVResyncMinutes);"""
)


# ============================================================
# MainFrm.h
# ============================================================

replace(
    "MainFrm.h",
    "\tvoid SeekTo(REFERENCE_TIME rt, bool bShowOSD = true);",
    """\tvoid SeekTo(REFERENCE_TIME rt, bool bShowOSD = true);

\t// Automatic keyframe-based A/V resynchronization.
\tREFERENCE_TIME m_rtAutoResyncElapsed = 0;
\tREFERENCE_TIME m_rtAutoResyncLastPos = -1;
\tREFERENCE_TIME m_rtAutoResyncTarget = -1;
\tULONGLONG m_autoResyncLastTick = 0;
\tint m_nAutoResyncInterval = 0;
\tbool m_bAutoResyncSeeking = false;

\tvoid ResetAutoResync();
\tbool UpdateAutoResync(REFERENCE_TIME rtNow, REFERENCE_TIME rtDuration);"""
)


# ============================================================
# MainFrm.cpp: playback timer integration
# ============================================================

replace(
    "MainFrm.cpp",
    """\t\t\t\t\t\tm_pMS->GetDuration(&rtDur);
\t\t\t\t\t\tm_pMS->GetCurrentPosition(&rtNow);""",
    """\t\t\t\t\t\tm_pMS->GetDuration(&rtDur);
\t\t\t\t\t\tif (SUCCEEDED(m_pMS->GetCurrentPosition(&rtNow))) {
\t\t\t\t\t\t\tif (UpdateAutoResync(rtNow, rtDur)) {
\t\t\t\t\t\t\t\treturn;
\t\t\t\t\t\t\t}
\t\t\t\t\t\t}"""
)


# ============================================================
# MainFrm.cpp: reset on media changes and playback stop
# ============================================================

replace(
    "MainFrm.cpp",
    """void CMainFrame::SetLoadState(MPC_LOADSTATE iState)
{""",
    """void CMainFrame::SetLoadState(MPC_LOADSTATE iState)
{
\tResetAutoResync();"""
)

replace(
    "MainFrm.cpp",
    """void CMainFrame::OnPlayStop()
{""",
    """void CMainFrame::OnPlayStop()
{
\tResetAutoResync();"""
)


# ============================================================
# MainFrm.cpp: reset after successful seeks
# ============================================================

replace(
    "MainFrm.cpp",
    """\t\tm_pMS->SetPositions(&rtPos, AM_SEEKING_AbsolutePositioning, nullptr, AM_SEEKING_NoPositioning);

\t\tif (m_bUseReclock) {""",
    """\t\tif (SUCCEEDED(m_pMS->SetPositions(&rtPos, AM_SEEKING_AbsolutePositioning, nullptr, AM_SEEKING_NoPositioning))) {
\t\t\tResetAutoResync();
\t\t}

\t\tif (m_bUseReclock) {"""
)


# ============================================================
# MainFrm.cpp: automatic resynchronization implementation
# ============================================================

replace(
    "MainFrm.cpp",
    "void CMainFrame::SeekTo(REFERENCE_TIME rtPos, bool bShowOSD/* = true*/)",
    r"""void CMainFrame::ResetAutoResync()
{
	m_rtAutoResyncElapsed = 0;
	m_rtAutoResyncLastPos = -1;
	m_rtAutoResyncTarget = -1;
	m_autoResyncLastTick = 0;
	m_nAutoResyncInterval = 0;
}

bool CMainFrame::UpdateAutoResync(
	REFERENCE_TIME rtNow,
	REFERENCE_TIME rtDuration)
{
	// SeekTo() invokes the playback timer itself.
	// Do not allow a seek to recursively trigger another seek.
	if (m_bAutoResyncSeeking) {
		return false;
	}

	const auto& s = AfxGetAppSettings();

	if (!s.bAutoAVResync
			|| m_eMediaLoadState != MLS_LOADED
			|| GetPlaybackMode() != PM_FILE
			|| m_bAudioOnly
			|| m_bShockwaveGraph
			|| rtDuration <= 0) {
		ResetAutoResync();
		return false;
	}

	const int interval = s.nAutoAVResyncMinutes;

	if (interval < 1 || interval > 120) {
		ResetAutoResync();
		return false;
	}

	// Changing the configured interval starts a fresh countdown.
	if (m_nAutoResyncInterval != interval) {
		ResetAutoResync();
		m_nAutoResyncInterval = interval;
	}

	// DirectShow media time is measured in 100-nanosecond units.
	constexpr REFERENCE_TIME kSecond = 10000000LL;
	constexpr REFERENCE_TIME kMillisecond = 10000LL;

	const REFERENCE_TIME rtInterval = interval * 60LL * kSecond;

	// Require a small amount of forward progress past the keyframe.
	constexpr REFERENCE_TIME rtMinOvershoot = 10 * kMillisecond;
	constexpr REFERENCE_TIME rtMaxOvershoot = 100 * kMillisecond;

	if (GetTimeFormat() != TIME_FORMAT_MEDIA_TIME) {
		ResetAutoResync();
		return false;
	}

	// Suspend the countdown during pauses, buffering, A/B repeat,
	// end-of-stream handling, and seek bar dragging.
	if (GetMediaState() != State_Running
			|| m_bBuffering
			|| m_bEndOfStream
			|| m_bGraphEventComplete
			|| m_abRepeatPositionAEnabled
			|| m_abRepeatPositionBEnabled
			|| ::GetCapture() == m_wndSeekBar.GetSafeHwnd()) {
		m_rtAutoResyncLastPos = -1;
		m_rtAutoResyncTarget = -1;
		m_autoResyncLastTick = 0;
		return false;
	}

	const ULONGLONG tick = ::GetTickCount64();

	// Establish a baseline after opening, seeking, or resuming.
	if (m_rtAutoResyncLastPos < 0) {
		m_rtAutoResyncLastPos = rtNow;
		m_autoResyncLastTick = tick;
		return false;
	}

	const REFERENCE_TIME rtDelta = rtNow - m_rtAutoResyncLastPos;
	const REFERENCE_TIME rtWallDelta =
		static_cast<REFERENCE_TIME>(tick - m_autoResyncLastTick)
		* kMillisecond;

	m_rtAutoResyncLastPos = rtNow;
	m_autoResyncLastTick = tick;

	// Detect discontinuities from seek paths that bypass SeekTo().
	if (rtDelta < -100 * kMillisecond
			|| rtDelta > 2 * rtWallDelta + 500 * kMillisecond) {
		ResetAutoResync();
		m_nAutoResyncInterval = interval;
		m_rtAutoResyncLastPos = rtNow;
		m_autoResyncLastTick = tick;
		return false;
	}

	// Count actual media progress, not time spent paused.
	if (rtDelta > 0) {
		m_rtAutoResyncElapsed += rtDelta;
	}

	if (m_rtAutoResyncElapsed < rtInterval) {
		return false;
	}

	// If a target keyframe was missed, wait for the following one.
	// Never rewind by more than the configured tolerance.
	if (m_rtAutoResyncTarget >= 0
			&& rtNow - m_rtAutoResyncTarget > rtMaxOvershoot) {
		DLog(L"[AutoAVResync] Missed keyframe; selecting next");
		m_rtAutoResyncTarget = -1;
	}

	// Select the next strictly upcoming keyframe.
	if (m_rtAutoResyncTarget < 0) {
		MatroskaLoadKeyFrames();

		if (m_kfs.empty()) {
			DLog(L"[AutoAVResync] No keyframe index available");
			ResetAutoResync();
			return false;
		}

		const auto it = std::upper_bound(
			m_kfs.cbegin(), m_kfs.cend(), rtNow);

		if (it == m_kfs.cend() || *it >= rtDuration) {
			DLog(L"[AutoAVResync] No upcoming keyframe");
			ResetAutoResync();
			return false;
		}

		m_rtAutoResyncTarget = *it;

		DLog(L"[AutoAVResync] Target keyframe: %I64d ms",
			m_rtAutoResyncTarget / kMillisecond);

		return false;
	}

	const REFERENCE_TIME rtOvershoot = rtNow - m_rtAutoResyncTarget;

	if (rtOvershoot < rtMinOvershoot) {
		return false;
	}

	// At this point the target was passed by 10-100 ms.
	const REFERENCE_TIME rtTarget = m_rtAutoResyncTarget;

	if (!ValidateSeek(rtTarget, rtDuration)) {
		ResetAutoResync();
		return false;
	}

	DLog(L"[AutoAVResync] Seeking to %I64d ms (rewind: %I64d ms)",
		rtTarget / kMillisecond,
		rtOvershoot / kMillisecond);

	// Reset before seeking so nested timer calls cannot retrigger it.
	ResetAutoResync();
	m_bAutoResyncSeeking = true;

	// Use the standard seek path, but suppress the seek OSD.
	SeekTo(rtTarget, false);

	m_bAutoResyncSeeking = false;

	return true;
}

void CMainFrame::SeekTo(REFERENCE_TIME rtPos, bool bShowOSD/* = true*/)"""
)


# ============================================================
# resource.h: new control IDs
# ============================================================

replace(
    "resource.h",
    "// Next default values for new objects",
    """#define IDC_AUTO_AV_RESYNC              22054
#define IDC_AUTO_AV_RESYNC_INTERVAL     22055

// Next default values for new objects"""
)

replace(
    "resource.h",
    "#define _APS_NEXT_CONTROL_VALUE         22054",
    "#define _APS_NEXT_CONTROL_VALUE         22056"
)


# ============================================================
# mplayerc.rc: playback settings controls
# ============================================================

replace(
    "mplayerc.rc",
    """    CONTROL         "Pause the video playback when minimized",IDC_CHECK5,
                    "Button",BS_AUTOCHECKBOX | WS_TABSTOP,10,221,280,9
END""",
    """    CONTROL         "Pause the video playback when minimized",IDC_CHECK5,
                    "Button",BS_AUTOCHECKBOX | WS_TABSTOP,10,221,280,9
    CONTROL         "Enable automatic A/V resynchronization",IDC_AUTO_AV_RESYNC,
                    "Button",BS_AUTOCHECKBOX | WS_TABSTOP,10,233,280,9
    LTEXT           "Resynchronization interval (minutes):",IDC_STATIC,20,248,150,8
    EDITTEXT        IDC_AUTO_AV_RESYNC_INTERVAL,175,245,35,13,ES_AUTOHSCROLL | ES_NUMBER
END"""
)


# ============================================================
# PPagePlayback.h
# ============================================================

replace(
    "PPagePlayback.h",
    "\tBOOL\t\tm_bFastSeek = FALSE;",
    """\tBOOL\t\tm_bFastSeek = FALSE;
\tBOOL\t\tm_bAutoAVResync = FALSE;
\tint\t\t\tm_nAutoAVResyncMinutes = 15;"""
)

replace(
    "PPagePlayback.h",
    "\tafx_msg void OnUpdateLoopNum(CCmdUI* pCmdUI);",
    """\tafx_msg void OnUpdateLoopNum(CCmdUI* pCmdUI);
\tafx_msg void OnAutoAVResyncChanged();
\tafx_msg void OnUpdateAutoAVResyncInterval(CCmdUI* pCmdUI);"""
)


# ============================================================
# PPagePlayback.cpp: DDX
# ============================================================

replace(
    "PPagePlayback.cpp",
    "\tDDX_Check(pDX, IDC_CHECK3, m_bFastSeek);",
    """\tDDX_Check(pDX, IDC_CHECK3, m_bFastSeek);

\t// Older translated resources may not contain these controls.
\tif (GetDlgItem(IDC_AUTO_AV_RESYNC)
\t\t\t&& GetDlgItem(IDC_AUTO_AV_RESYNC_INTERVAL)) {
\t\tDDX_Check(pDX, IDC_AUTO_AV_RESYNC, m_bAutoAVResync);
\t\tDDX_Text(pDX, IDC_AUTO_AV_RESYNC_INTERVAL, m_nAutoAVResyncMinutes);
\t\tDDV_MinMaxInt(pDX, m_nAutoAVResyncMinutes, 1, 120);
\t}"""
)


# ============================================================
# PPagePlayback.cpp: message handlers
# ============================================================

replace(
    "PPagePlayback.cpp",
    "\tON_UPDATE_COMMAND_UI(IDC_EDIT3, OnUpdateTrackOrder)",
    """\tON_UPDATE_COMMAND_UI(IDC_EDIT3, OnUpdateTrackOrder)
\tON_BN_CLICKED(IDC_AUTO_AV_RESYNC, OnAutoAVResyncChanged)
\tON_EN_CHANGE(IDC_AUTO_AV_RESYNC_INTERVAL, OnAutoAVResyncChanged)
\tON_UPDATE_COMMAND_UI(IDC_AUTO_AV_RESYNC_INTERVAL, OnUpdateAutoAVResyncInterval)"""
)

replace(
    "PPagePlayback.cpp",
    "\tm_bFastSeek = s.fFastSeek;",
    """\tm_bFastSeek = s.fFastSeek;
\tm_bAutoAVResync = s.bAutoAVResync;
\tm_nAutoAVResyncMinutes = s.nAutoAVResyncMinutes;"""
)

replace(
    "PPagePlayback.cpp",
    """BOOL CPPagePlayback::OnApply()
{
\tUpdateData();""",
    """BOOL CPPagePlayback::OnApply()
{
\tif (!UpdateData(TRUE)) {
\t\treturn FALSE;
\t}"""
)

replace(
    "PPagePlayback.cpp",
    "\ts.fFastSeek = !!m_bFastSeek;",
    """\ts.fFastSeek = !!m_bFastSeek;

\tif (GetDlgItem(IDC_AUTO_AV_RESYNC)
\t\t\t&& GetDlgItem(IDC_AUTO_AV_RESYNC_INTERVAL)) {
\t\ts.bAutoAVResync = !!m_bAutoAVResync;
\t\ts.nAutoAVResyncMinutes = m_nAutoAVResyncMinutes;
\t}"""
)

replace(
    "PPagePlayback.cpp",
    "void CPPagePlayback::OnUpdateLoopNum(CCmdUI* pCmdUI)",
    """void CPPagePlayback::OnAutoAVResyncChanged()
{
\tSetModified();
}

void CPPagePlayback::OnUpdateAutoAVResyncInterval(CCmdUI* pCmdUI)
{
\tpCmdUI->Enable(!!IsDlgButtonChecked(IDC_AUTO_AV_RESYNC));
}

void CPPagePlayback::OnUpdateLoopNum(CCmdUI* pCmdUI)"""
)


# ============================================================
# Write only after all replacements have been validated.
# ============================================================

for name, (path, text, encoding, newline) in files.items():
    path.write_bytes(text.replace("\n", newline).encode(encoding))
    print(f"Modified: {path}")

print()
print("Automatic A/V resynchronization patch applied.")
print("Run git diff --check and git diff to review.")
