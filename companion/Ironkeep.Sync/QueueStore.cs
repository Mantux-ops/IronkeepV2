using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Data.Sqlite;

namespace Ironkeep
{
    public static class SyncState
    {
        public const string Pending = "Pending";
        public const string Sending = "Sending";
        public const string Confirmed = "Confirmed";
        public const string RetryScheduled = "RetryScheduled";
        public const string FailedPermanent = "FailedPermanent";
    }

    public sealed class QueueItem
    {
        public string Id = "";
        public string GuildId = "";
        public string Body;
        public string BodyHash = "";
        public string SourcePath = "";
        public string State = "";
        public int Attempts;
        public string NextAttemptAt;
        public string LastError;
    }

    public static class SyncPaths
    {
        public static string AppDirectory()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Ironkeep");
        }

        public static string QueueDatabase()
        {
            return Path.Combine(AppDirectory(), "companion-queue.sqlite");
        }
    }

    /// <summary>
    /// One SQLite file of immutable report snapshots. State changes are single transactions.
    /// A file that is not a database is renamed aside and is not imported.
    /// </summary>
    public sealed class QueueStore : IDisposable
    {
        readonly SqliteConnection _connection;
        readonly object _gate = new object();

        QueueStore(SqliteConnection connection, bool corruptionDetected, string preservedCorruptPath)
        {
            _connection = connection;
            CorruptionDetected = corruptionDetected;
            PreservedCorruptPath = preservedCorruptPath ?? "";
        }

        public bool CorruptionDetected { get; private set; }
        public string PreservedCorruptPath { get; private set; }
        public bool UnsentReportsRecovered { get { return !CorruptionDetected; } }

        public static QueueStore Open(string path)
        {
            if (path == null || path.Trim().Length == 0) throw new ArgumentException("Queue path is required.");
            string directory = Path.GetDirectoryName(Path.GetFullPath(path));
            if (directory == null || directory.Length == 0) throw new ArgumentException("Queue path is required.");
            Directory.CreateDirectory(directory);
            string sidecar = path + ".corruption";
            bool corrupt = false;
            string preserved = "";
            if (File.Exists(sidecar))
            {
                corrupt = true;
                preserved = ReadSidecar(sidecar);
            }
            if (File.Exists(path) && !DatabaseReadable(path))
            {
                preserved = Preserve(path);
                File.WriteAllText(sidecar, preserved + Environment.NewLine);
                Restrict(sidecar);
                corrupt = true;
            }
            var connection = new SqliteConnection(ConnectionString(path));
            connection.Open();
            using (var pragma = connection.CreateCommand())
            {
                pragma.CommandText = "PRAGMA journal_mode=WAL;";
                pragma.ExecuteNonQuery();
            }
            var store = new QueueStore(connection, corrupt, preserved);
            store.EnsureSchema();
            store.ResetSendingToPending();
            Restrict(path);
            return store;
        }

        public void Dispose()
        {
            _connection.Dispose();
        }

        public QueueItem Enqueue(string guildId, string sourcePath, string body)
        {
            if (guildId == null || guildId.Trim().Length == 0) throw new ArgumentException("Guild is required.");
            if (body == null) throw new ArgumentException("Snapshot is required.");
            string hash = ReportHash.Of(body);
            string now = Stamp(DateTime.UtcNow);
            lock (_gate)
            {
                QueueItem existing = InsertOrFind(guildId, sourcePath, body, hash, now);
                if (existing != null) return existing;
                existing = InsertOrFind(guildId, sourcePath, body, hash, now);
                if (existing == null) throw new InvalidOperationException("Could not store the snapshot.");
                return existing;
            }
        }

        QueueItem InsertOrFind(string guildId, string sourcePath, string body, string hash, string now)
        {
            using (var tx = _connection.BeginTransaction())
            {
                QueueItem existing = Find(guildId, hash, tx);
                if (existing != null)
                {
                    tx.Commit();
                    return existing;
                }
                var item = new QueueItem();
                item.Id = Guid.NewGuid().ToString("N");
                item.GuildId = guildId;
                item.Body = body;
                item.BodyHash = hash;
                item.SourcePath = sourcePath ?? "";
                item.State = SyncState.Pending;
                item.Attempts = 0;
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.Transaction = tx;
                    cmd.CommandText = @"INSERT INTO items
                        (id, guild_id, body, body_hash, source_path, state, attempts, next_attempt_at, last_error, created_at, updated_at, confirmed_at)
                        VALUES ($id, $guild, $body, $hash, $path, $state, 0, NULL, NULL, $now, $now, NULL)";
                    cmd.Parameters.AddWithValue("$id", item.Id);
                    cmd.Parameters.AddWithValue("$guild", item.GuildId);
                    cmd.Parameters.AddWithValue("$body", item.Body);
                    cmd.Parameters.AddWithValue("$hash", item.BodyHash);
                    cmd.Parameters.AddWithValue("$path", item.SourcePath);
                    cmd.Parameters.AddWithValue("$state", item.State);
                    cmd.Parameters.AddWithValue("$now", now);
                    try
                    {
                        cmd.ExecuteNonQuery();
                    }
                    catch (SqliteException)
                    {
                        tx.Rollback();
                        return null;
                    }
                }
                tx.Commit();
                return item;
            }
        }

        public QueueItem Get(string id)
        {
            lock (_gate)
            {
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.CommandText = "SELECT * FROM items WHERE id = $id";
                    cmd.Parameters.AddWithValue("$id", id ?? "");
                    using (var reader = cmd.ExecuteReader())
                    {
                        if (!reader.Read()) return null;
                        return ReadItem(reader);
                    }
                }
            }
        }

        public List<QueueItem> Due(DateTime utcNow)
        {
            string now = Stamp(utcNow);
            var items = new List<QueueItem>();
            lock (_gate)
            {
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.CommandText = @"SELECT * FROM items
                        WHERE state = $pending
                           OR (state = $retry AND (next_attempt_at IS NULL OR next_attempt_at <= $now))
                        ORDER BY created_at";
                    cmd.Parameters.AddWithValue("$pending", SyncState.Pending);
                    cmd.Parameters.AddWithValue("$retry", SyncState.RetryScheduled);
                    cmd.Parameters.AddWithValue("$now", now);
                    using (var reader = cmd.ExecuteReader())
                    {
                        while (reader.Read()) items.Add(ReadItem(reader));
                    }
                }
            }
            return items;
        }

        public void MarkSending(string id, DateTime utcNow)
        {
            lock (_gate)
            {
                using (var tx = _connection.BeginTransaction())
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.Transaction = tx;
                    cmd.CommandText = @"UPDATE items
                        SET state = $state, attempts = attempts + 1, next_attempt_at = NULL, updated_at = $now
                        WHERE id = $id AND state IN ($pending, $retry)";
                    cmd.Parameters.AddWithValue("$state", SyncState.Sending);
                    cmd.Parameters.AddWithValue("$now", Stamp(utcNow));
                    cmd.Parameters.AddWithValue("$id", id);
                    cmd.Parameters.AddWithValue("$pending", SyncState.Pending);
                    cmd.Parameters.AddWithValue("$retry", SyncState.RetryScheduled);
                    if (cmd.ExecuteNonQuery() != 1) throw new InvalidOperationException("Item is not waiting to send.");
                    tx.Commit();
                }
            }
        }

        public void MarkConfirmed(string id, DateTime utcNow)
        {
            string now = Stamp(utcNow);
            lock (_gate)
            {
                using (var tx = _connection.BeginTransaction())
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.Transaction = tx;
                    cmd.CommandText = @"UPDATE items
                        SET state = $state, body = NULL, confirmed_at = $now, updated_at = $now, last_error = NULL, next_attempt_at = NULL
                        WHERE id = $id";
                    cmd.Parameters.AddWithValue("$state", SyncState.Confirmed);
                    cmd.Parameters.AddWithValue("$now", now);
                    cmd.Parameters.AddWithValue("$id", id);
                    cmd.ExecuteNonQuery();
                    tx.Commit();
                }
            }
        }

        public void MarkRetry(string id, DateTime nextAttemptUtc, string error, DateTime utcNow)
        {
            lock (_gate)
            {
                using (var tx = _connection.BeginTransaction())
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.Transaction = tx;
                    cmd.CommandText = @"UPDATE items
                        SET state = $state, next_attempt_at = $next, last_error = $error, updated_at = $now
                        WHERE id = $id";
                    cmd.Parameters.AddWithValue("$state", SyncState.RetryScheduled);
                    cmd.Parameters.AddWithValue("$next", Stamp(nextAttemptUtc));
                    cmd.Parameters.AddWithValue("$error", error ?? "");
                    cmd.Parameters.AddWithValue("$now", Stamp(utcNow));
                    cmd.Parameters.AddWithValue("$id", id);
                    cmd.ExecuteNonQuery();
                    tx.Commit();
                }
            }
        }

        public void MarkFailed(string id, string error, DateTime utcNow)
        {
            lock (_gate)
            {
                using (var tx = _connection.BeginTransaction())
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.Transaction = tx;
                    cmd.CommandText = @"UPDATE items
                        SET state = $state, last_error = $error, next_attempt_at = NULL, updated_at = $now
                        WHERE id = $id";
                    cmd.Parameters.AddWithValue("$state", SyncState.FailedPermanent);
                    cmd.Parameters.AddWithValue("$error", error ?? "");
                    cmd.Parameters.AddWithValue("$now", Stamp(utcNow));
                    cmd.Parameters.AddWithValue("$id", id);
                    cmd.ExecuteNonQuery();
                    tx.Commit();
                }
            }
        }

        public void RetryFailed(string id, DateTime utcNow)
        {
            lock (_gate)
            {
                using (var tx = _connection.BeginTransaction())
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.Transaction = tx;
                    cmd.CommandText = @"UPDATE items
                        SET state = $state, next_attempt_at = NULL, last_error = NULL, updated_at = $now
                        WHERE id = $id AND state = $failed AND body IS NOT NULL";
                    cmd.Parameters.AddWithValue("$state", SyncState.Pending);
                    cmd.Parameters.AddWithValue("$now", Stamp(utcNow));
                    cmd.Parameters.AddWithValue("$id", id);
                    cmd.Parameters.AddWithValue("$failed", SyncState.FailedPermanent);
                    cmd.ExecuteNonQuery();
                    tx.Commit();
                }
            }
        }

        public Dictionary<string, int> Counts()
        {
            var counts = new Dictionary<string, int>();
            lock (_gate)
            {
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.CommandText = "SELECT state, COUNT(*) FROM items GROUP BY state";
                    using (var reader = cmd.ExecuteReader())
                    {
                        while (reader.Read()) counts[reader.GetString(0)] = reader.GetInt32(1);
                    }
                }
            }
            return counts;
        }

        void ResetSendingToPending()
        {
            lock (_gate)
            {
                using (var tx = _connection.BeginTransaction())
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.Transaction = tx;
                    cmd.CommandText = "UPDATE items SET state = $pending, updated_at = $now WHERE state = $sending";
                    cmd.Parameters.AddWithValue("$pending", SyncState.Pending);
                    cmd.Parameters.AddWithValue("$now", Stamp(DateTime.UtcNow));
                    cmd.Parameters.AddWithValue("$sending", SyncState.Sending);
                    cmd.ExecuteNonQuery();
                    tx.Commit();
                }
            }
        }

        void EnsureSchema()
        {
            using (var cmd = _connection.CreateCommand())
            {
                cmd.CommandText = @"
                    CREATE TABLE IF NOT EXISTS items (
                        id TEXT PRIMARY KEY,
                        guild_id TEXT NOT NULL,
                        body TEXT,
                        body_hash TEXT NOT NULL,
                        source_path TEXT NOT NULL,
                        state TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        next_attempt_at TEXT,
                        last_error TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        confirmed_at TEXT
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS items_guild_hash ON items (guild_id, body_hash);";
                cmd.ExecuteNonQuery();
            }
        }

        QueueItem Find(string guildId, string hash, SqliteTransaction tx)
        {
            using (var cmd = _connection.CreateCommand())
            {
                cmd.Transaction = tx;
                cmd.CommandText = "SELECT * FROM items WHERE guild_id = $guild AND body_hash = $hash";
                cmd.Parameters.AddWithValue("$guild", guildId);
                cmd.Parameters.AddWithValue("$hash", hash);
                using (var reader = cmd.ExecuteReader())
                {
                    if (!reader.Read()) return null;
                    return ReadItem(reader);
                }
            }
        }

        static QueueItem ReadItem(SqliteDataReader reader)
        {
            var item = new QueueItem();
            item.Id = reader.GetString(reader.GetOrdinal("id"));
            item.GuildId = reader.GetString(reader.GetOrdinal("guild_id"));
            item.Body = reader.IsDBNull(reader.GetOrdinal("body")) ? null : reader.GetString(reader.GetOrdinal("body"));
            item.BodyHash = reader.GetString(reader.GetOrdinal("body_hash"));
            item.SourcePath = reader.GetString(reader.GetOrdinal("source_path"));
            item.State = reader.GetString(reader.GetOrdinal("state"));
            item.Attempts = reader.GetInt32(reader.GetOrdinal("attempts"));
            int next = reader.GetOrdinal("next_attempt_at");
            item.NextAttemptAt = reader.IsDBNull(next) ? null : reader.GetString(next);
            int error = reader.GetOrdinal("last_error");
            item.LastError = reader.IsDBNull(error) ? null : reader.GetString(error);
            return item;
        }

        static string ConnectionString(string path)
        {
            return "Data Source=" + path + ";Pooling=False";
        }

        static bool DatabaseReadable(string path)
        {
            SqliteConnection connection = null;
            try
            {
                connection = new SqliteConnection(ConnectionString(path));
                connection.Open();
                using (var cmd = connection.CreateCommand())
                {
                    cmd.CommandText = "PRAGMA integrity_check;";
                    object result = cmd.ExecuteScalar();
                    return result != null && string.Equals(result.ToString(), "ok", StringComparison.OrdinalIgnoreCase);
                }
            }
            catch (SqliteException)
            {
                return false;
            }
            catch (IOException)
            {
                return false;
            }
            finally
            {
                if (connection != null) connection.Dispose();
            }
        }

        static string Preserve(string path)
        {
            string directory = Path.GetDirectoryName(path);
            string stamp = DateTime.UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'", CultureInfo.InvariantCulture);
            string dest = Path.Combine(directory, "queue-corrupt-" + stamp + ".sqlite");
            int n = 0;
            while (File.Exists(dest))
            {
                n++;
                dest = Path.Combine(directory, "queue-corrupt-" + stamp + "-" + n + ".sqlite");
            }
            File.Move(path, dest);
            MoveIfExists(path + "-wal", dest + "-wal");
            MoveIfExists(path + "-shm", dest + "-shm");
            Restrict(dest);
            return dest;
        }

        static void MoveIfExists(string source, string dest)
        {
            if (!File.Exists(source)) return;
            File.Move(source, dest);
            Restrict(dest);
        }

        static string ReadSidecar(string sidecar)
        {
            try
            {
                string text = File.ReadAllText(sidecar).Trim();
                return text;
            }
            catch (IOException)
            {
                return "";
            }
        }

        static string Stamp(DateTime utc)
        {
            return utc.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", CultureInfo.InvariantCulture);
        }

        public static void Restrict(string path)
        {
            try
            {
                if (!File.Exists(path)) return;
                if (OperatingSystem.IsWindows())
                {
                    var info = new FileInfo(path);
                    FileSecurity security = info.GetAccessControl();
                    security.SetAccessRuleProtection(true, false);
                    security.AddAccessRule(new FileSystemAccessRule(
                        WindowsIdentity.GetCurrent().User,
                        FileSystemRights.FullControl,
                        AccessControlType.Allow));
                    info.SetAccessControl(security);
                    return;
                }
                File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            }
            catch (UnauthorizedAccessException)
            {
            }
            catch (IOException)
            {
            }
            catch (PlatformNotSupportedException)
            {
            }
        }
    }
}
