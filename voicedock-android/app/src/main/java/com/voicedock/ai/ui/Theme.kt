package com.voicedock.ai.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Light = lightColorScheme(primary = Color(0xFF6750A4), secondary = Color(0xFF006A6A), surfaceVariant = Color(0xFFE7E0EC))
private val Dark = darkColorScheme(primary = Color(0xFFD0BCFF), secondary = Color(0xFF4FD8D8))
@Composable fun VoiceDockTheme(content: @Composable () -> Unit) = MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, content = content)
