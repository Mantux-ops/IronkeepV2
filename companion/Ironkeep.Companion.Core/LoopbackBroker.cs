using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace Ironkeep.Companion
{
    public sealed class LoopbackHit
    {
        public string Kind = "";
        public string Code = "";
        public string State = "";
        public string Error = "";
    }

    /// <summary>
    /// One-shot callback listener. It binds only to 127.0.0.1 and does not record the request.
    /// </summary>
    public sealed class LoopbackBroker : IDisposable
    {
        readonly TcpListener _listener;
        readonly ManualResetEvent _done = new ManualResetEvent(false);
        readonly Thread _thread;
        LoopbackHit _hit;
        int _finished;
        bool _disposed;

        LoopbackBroker(TcpListener listener)
        {
            _listener = listener;
            _thread = new Thread(AcceptLoop);
            _thread.IsBackground = true;
            _thread.Start();
        }

        public int Port { get { return ((IPEndPoint)_listener.LocalEndpoint).Port; } }

        public string RedirectUri { get { return "http://127.0.0.1:" + Port.ToString() + "/callback"; } }

        public static LoopbackBroker Start()
        {
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            IPEndPoint endpoint = (IPEndPoint)listener.LocalEndpoint;
            if (!endpoint.Address.Equals(IPAddress.Loopback))
            {
                listener.Stop();
                throw new InvalidOperationException("The callback listener was not bound to 127.0.0.1.");
            }
            return new LoopbackBroker(listener);
        }

        public LoopbackHit Wait(TimeSpan timeout, CancellationToken cancel)
        {
            DateTime deadline = DateTime.UtcNow + timeout;
            while (DateTime.UtcNow < deadline)
            {
                if (cancel.IsCancellationRequested)
                {
                    Stop();
                    return new LoopbackHit { Kind = "cancelled" };
                }
                if (_done.WaitOne(50)) return _hit ?? new LoopbackHit { Kind = "cancelled" };
            }
            Stop();
            return new LoopbackHit { Kind = "timeout" };
        }

        public void Stop()
        {
            try
            {
                _listener.Stop();
            }
            catch (Exception)
            {
            }
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Stop();
            _done.Dispose();
        }

        void AcceptLoop()
        {
            try
            {
                while (true)
                {
                    TcpClient client;
                    try
                    {
                        client = _listener.AcceptTcpClient();
                    }
                    catch (Exception)
                    {
                        Finish(new LoopbackHit { Kind = "cancelled" });
                        return;
                    }
                    try
                    {
                        LoopbackHit hit;
                        if (TryHandle(client, out hit))
                        {
                            Finish(hit);
                            return;
                        }
                    }
                    catch (Exception)
                    {
                    }
                    finally
                    {
                        try { client.Close(); }
                        catch (Exception) { }
                    }
                }
            }
            catch (Exception)
            {
                Finish(new LoopbackHit { Kind = "cancelled" });
            }
        }

        static bool TryHandle(TcpClient client, out LoopbackHit hit)
        {
            hit = null;
            IPEndPoint remote = client.Client.RemoteEndPoint as IPEndPoint;
            if (remote == null || !IPAddress.IsLoopback(remote.Address)) return false;
            client.ReceiveTimeout = 5000;
            client.SendTimeout = 5000;
            string header = ReadHeader(client);
            if (header.Length == 0) return false;
            int lineEnd = header.IndexOf("\r\n", StringComparison.Ordinal);
            string request = lineEnd < 0 ? header : header.Substring(0, lineEnd);
            string[] parts = request.Split(' ');
            if (parts.Length < 2 || !string.Equals(parts[0], "GET", StringComparison.Ordinal))
            {
                Write(client, 400, "This callback could not be read.");
                return false;
            }
            string target = parts[1];
            string path = target;
            string query = "";
            int question = target.IndexOf('?');
            if (question >= 0)
            {
                path = target.Substring(0, question);
                query = target.Substring(question + 1);
            }
            if (!string.Equals(path, "/callback", StringComparison.Ordinal))
            {
                Write(client, 404, "Not found.");
                return false;
            }
            Dictionary<string, string> fields = ParseQuery(query);
            string code;
            string state;
            string error;
            fields.TryGetValue("code", out code);
            fields.TryGetValue("state", out state);
            fields.TryGetValue("error", out error);
            Write(client, 200, "You can close this window and return to Ironkeep Companion.");
            hit = new LoopbackHit();
            hit.Kind = "callback";
            hit.Code = code ?? "";
            hit.State = state ?? "";
            hit.Error = error ?? "";
            return true;
        }

        static string ReadHeader(TcpClient client)
        {
            var buffer = new byte[8192];
            int used = 0;
            NetworkStream stream = client.GetStream();
            while (used < buffer.Length)
            {
                int read;
                try { read = stream.Read(buffer, used, buffer.Length - used); }
                catch (Exception) { return ""; }
                if (read <= 0) break;
                used += read;
                string text = Encoding.ASCII.GetString(buffer, 0, used);
                if (text.IndexOf("\r\n\r\n", StringComparison.Ordinal) >= 0) return text;
            }
            return "";
        }

        static Dictionary<string, string> ParseQuery(string query)
        {
            var map = new Dictionary<string, string>(StringComparer.Ordinal);
            if (query == null || query.Length == 0) return map;
            string[] parts = query.Split('&');
            for (int i = 0; i < parts.Length; i++)
            {
                string part = parts[i];
                if (part.Length == 0) continue;
                int eq = part.IndexOf('=');
                string key = Uri.UnescapeDataString(eq < 0 ? part : part.Substring(0, eq));
                string value = eq < 0 ? "" : Uri.UnescapeDataString(part.Substring(eq + 1).Replace("+", " "));
                if (!map.ContainsKey(key)) map[key] = value;
            }
            return map;
        }

        static void Write(TcpClient client, int status, string message)
        {
            string title = status == 200 ? "OK" : status == 404 ? "Not Found" : "Bad Request";
            string body = "<!DOCTYPE html><html><body><p>" + message + "</p></body></html>";
            byte[] payload = Encoding.UTF8.GetBytes(body);
            string head = "HTTP/1.1 " + status.ToString() + " " + title + "\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: " + payload.Length.ToString() + "\r\nConnection: close\r\n\r\n";
            byte[] prefix = Encoding.ASCII.GetBytes(head);
            NetworkStream stream = client.GetStream();
            stream.Write(prefix, 0, prefix.Length);
            stream.Write(payload, 0, payload.Length);
            stream.Flush();
        }

        void Finish(LoopbackHit hit)
        {
            if (Interlocked.CompareExchange(ref _finished, 1, 0) != 0) return;
            _hit = hit;
            try { _done.Set(); }
            catch (ObjectDisposedException) { }
        }
    }
}
