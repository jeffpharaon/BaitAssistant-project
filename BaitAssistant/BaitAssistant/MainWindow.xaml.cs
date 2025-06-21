// MainWindow.xaml.cs
using System;
using System.Collections.ObjectModel;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media.Animation;
using NAudio.Wave;
using WebSocketSharp;                                  // WebSocketSharp
using WebSocketClient = WebSocketSharp.WebSocket;      // псевдоним

namespace BaitAssistant
{
	public partial class MainWindow : Window
	{
		// HTTP-клиент для /command/
		private static readonly HttpClient _http = new HttpClient
		{
			BaseAddress = new Uri("http://127.0.0.1:8000/")
		};

		// История команд
		private readonly ObservableCollection<string> _history
			= new ObservableCollection<string>();

		// Анимация микрофона
		private readonly Storyboard _micPulse;

		// NAudio-захват
		private WaveInEvent _waveIn;

		// WebSocket-клиент к /asr/ws
		private WebSocketClient _ws;

		// Флаг «слушаем»
		private bool _listening;

		public MainWindow()
		{
			InitializeComponent();

			HistoryList.ItemsSource = _history;

			_micPulse = (Storyboard)Resources["MicPulse"];

			ShowStatus(listen: false, processing: false, result: false);
		}

		private void ShowStatus(bool listen, bool processing, bool result)
		{
			ListenLb.Visibility = listen ? Visibility.Visible : Visibility.Hidden;
			ProcessingLb.Visibility = processing ? Visibility.Visible : Visibility.Hidden;
			ResultLb.Visibility = result ? Visibility.Visible : Visibility.Hidden;
		}

		// Клик по микрофону
		private void MicButton_Click(object sender, RoutedEventArgs e)
		{
			if (_listening)
				StopListening();
			else
				StartListening();
		}

		private void StartListening()
		{
			if (_listening) return;
			_listening = true;

			Dispatcher.Invoke(() =>
			{
				TranscribedTextBlock.Text = "";
				_history.Insert(0, "Байт слушает...");
				_micPulse.Begin();
				ShowStatus(listen: true, processing: false, result: false);
			});

			// Настраиваем NAudio, но не стартуем
			_waveIn = new WaveInEvent
			{
				DeviceNumber = 0,
				WaveFormat = new WaveFormat(16000, 16, 1),
				BufferMilliseconds = 200
			};
			_waveIn.DataAvailable += WaveIn_DataAvailable;

			// Создаём WS и ждём OnOpen
			_ws = new WebSocketClient("ws://127.0.0.1:8000/asr/ws");
			_ws.OnOpen += (s, ev) =>
			{
				// только после открытия сокета — стартуем запись
				_waveIn.StartRecording();
			};
			_ws.OnMessage += Ws_OnMessage;
			_ws.OnError += (s, ev) =>
			{
				// можно залогировать ev.Message
			};
			_ws.Connect();
		}

		private void StopListening()
		{
			if (!_listening) return;
			_listening = false;

			_waveIn?.StopRecording();
			_waveIn?.Dispose();
			_waveIn = null;

			_ws?.Close();
			_ws = null;

			Dispatcher.Invoke(() =>
			{
				_micPulse.Stop();
				MicButton.Opacity = 1.0;
				if (_history.Count > 0 && _history[0] == "Байт слушает...")
					_history.RemoveAt(0);

				ShowStatus(listen: false, processing: false, result: false);
			});
		}

		// Шлём PCM-чанк, только если WS открыт
		private void WaveIn_DataAvailable(object sender, WaveInEventArgs e)
		{
			if (_ws != null && _ws.ReadyState == WebSocketState.Open)
			{
				try
				{
					_ws.Send(e.Buffer);
				}
				catch
				{
					// проглатываем ошибку
				}
			}
		}

		// Пришёл JSON {"partial":...} или {"final":...}
		private void Ws_OnMessage(object sender, MessageEventArgs e)
		{
			var doc = JsonDocument.Parse(e.Data);

			if (doc.RootElement.TryGetProperty("partial", out var p))
			{
				string partial = p.GetString() ?? "";
				Dispatcher.Invoke(() =>
				{
					TranscribedTextBlock.Text = partial;
				});
			}
			else if (doc.RootElement.TryGetProperty("final", out var f))
			{
				string cmd = f.GetString() ?? "";
				Dispatcher.Invoke(() =>
				{
					TranscribedTextBlock.Text = cmd;
					_history.Insert(0, "Я (голос): " + cmd);
				});

				StopListening();
				_ = SendToServer(cmd);
			}
		}

		// Отправка текстовой команды
		private async void SendTextButton_Click(object sender, RoutedEventArgs e)
		{
			var raw = TextCommandBox.Text.Trim();
			if (string.IsNullOrEmpty(raw)) return;

			Dispatcher.Invoke(() =>
			{
				TranscribedTextBlock.Text = raw;
				_history.Insert(0, "Я (текст): " + raw);
			});

			await SendToServer(raw);
		}

		// HTTP POST /command/
		private async Task SendToServer(string cmd)
		{
			var full = cmd.StartsWith("Байт", StringComparison.OrdinalIgnoreCase)
					   ? cmd
					   : "Байт, " + cmd;

			var payload = new { text = full };
			string json = JsonSerializer.Serialize(payload);
			using var content = new StringContent(json, Encoding.UTF8, "application/json");

			try
			{
				var resp = await _http.PostAsync("command/", content);
				resp.EnsureSuccessStatusCode();

				string body = await resp.Content.ReadAsStringAsync();
				var result = JsonSerializer.Deserialize<CommandResponse>(body);

				Dispatcher.Invoke(() =>
				{
					TranscribedTextBlock.Text = result?.message ?? "";
					_history.Insert(0, "Байт: " + (result?.message ?? ""));
					ShowStatus(listen: false, processing: true, result: true);
				});
			}
			catch (Exception ex)
			{
				Dispatcher.Invoke(() =>
				{
					TranscribedTextBlock.Text = "Ошибка: " + ex.Message;
					_history.Insert(0, "Ошибка связи: " + ex.Message);
					ShowStatus(listen: false, processing: true, result: true);
				});
			}
		}

		// Кнопка «Настройки»
		private void SettingsButton_Click(object sender, RoutedEventArgs e)
		{
			if (SettingsOverlay.Visibility == Visibility.Collapsed)
			{
				SettingsOverlay.Visibility = Visibility.Visible;
				var fadeIn = new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(300));
				SettingsOverlay.BeginAnimation(OpacityProperty, fadeIn);
			}
			else
			{
				var fadeOut = new DoubleAnimation(1, 0, TimeSpan.FromMilliseconds(200));
				fadeOut.Completed += (s, a) => SettingsOverlay.Visibility = Visibility.Collapsed;
				SettingsOverlay.BeginAnimation(OpacityProperty, fadeOut);
			}
		}

		// Модель ответа
		private class CommandResponse
		{
			public string intent { get; set; }
			public bool status { get; set; }
			public string message { get; set; }
		}
	}
}
