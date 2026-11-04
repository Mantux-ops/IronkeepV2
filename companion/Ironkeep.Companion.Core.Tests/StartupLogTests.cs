using System;
using System.IO;
using Ironkeep.Companion;
using Xunit;

namespace Ironkeep.Companion.Core.Tests
{
    public sealed class StartupLogTests : IDisposable
    {
        readonly string _root;

        public StartupLogTests()
        {
            _root = Path.Combine(Path.GetTempPath(), "ironkeep-log-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            StartupLog.DirectoryOverride = _root;
        }

        public void Dispose()
        {
            StartupLog.DirectoryOverride = null;
            try { Directory.Delete(_root, true); }
            catch (Exception) { }
        }

        [Fact]
        public void RedactRemovesCompanionSecrets()
        {
            string raw = "token ika.access-token-should-not-be-stored-raw and ikr.refresh-token-should-not-be-stored-raw ikn.one-time-code dpapi:QUJDREVG bearer guild-key";
            string clean = StartupLog.Redact(raw);
            Assert.DoesNotContain("ika.access", clean);
            Assert.DoesNotContain("ikr.refresh", clean);
            Assert.DoesNotContain("ikn.one-time", clean);
            Assert.DoesNotContain("QUJDREVG", clean);
            Assert.DoesNotContain("guild-key", clean);
            Assert.Contains("[redacted]", clean);
        }

        [Fact]
        public void FatalExceptionIsWrittenWithoutTheSecret()
        {
            var inner = new InvalidOperationException("stored ikr.refresh-token-should-not-be-stored-raw");
            var error = new IOException("open failed", inner);
            StartupLog.WriteException("fatal", error);
            string text = File.ReadAllText(StartupLog.FilePath());
            Assert.Contains("fatal", text);
            Assert.Contains("System.IO.IOException", text);
            Assert.Contains("System.InvalidOperationException", text);
            Assert.Contains("open failed", text);
            Assert.DoesNotContain("ikr.refresh", text);
            Assert.Contains("[redacted]", text);
        }
    }
}
