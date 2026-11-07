using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
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
        public string CreatedAt;
        public string UpdatedAt;
        public string ConfirmedAt;
        public string Kind = "attendance";
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
        readonly FileStream _lock;
        readonly object _gate = new object();

        QueueStore(SqliteConnection connection, FileStream gate, bool corruptionDetected, string preservedCorruptPath)
        {
            _connection = connection;
            _lock = gate;
            CorruptionDetected = corruptionDetected;
            PreservedCorruptPath = preservedCorruptPath ?? "";
        }

        public bool CorruptionDetected { get; private set; }
        public string PreservedCorruptPath { get; private set; }
        public bool UnsentReportsRecovered { get { return !CorruptionDetected; } }

        public static QueueStore Open(string path)
        {
            if (path == null || path.Trim().Length == 0) throw new ArgumentException("Queue path is required.");
            string full = Path.GetFullPath(path);
            string directory = Path.GetDirectoryName(full);
            if (directory == null || directory.Length == 0) throw new ArgumentException("Queue path is required.");
            Directory.CreateDirectory(directory);
            SecureDirectory(directory);
            FileStream gate = null;
            SqliteConnection connection = null;
            try
            {
                gate = Acquire(full + ".lock");
                SecureFile(full + ".lock");
                bool corrupt;
                string preserved;
                RecoverIfNeeded(full, out corrupt, out preserved);
                connection = OpenDatabase(full);
                var store = new QueueStore(connection, gate, corrupt, preserved);
                store.EnsureSchema();
                store.ResetSendingToPending();
                SecureFile(full);
                SecureIfExists(full + "-wal");
                SecureIfExists(full + "-shm");
                SecureIfExists(full + ".corruption");
                connection = null;
                gate = null;
                return store;
            }
            catch
            {
                if (connection != null) connection.Dispose();
                if (gate != null) gate.Dispose();
                throw;
            }
        }

        public static void WritePendingRecoveryMarker(string queuePath, string destinationPath)
        {
            if (queuePath == null || queuePath.Trim().Length == 0) throw new ArgumentException("Queue path is required.");
            if (destinationPath == null || destinationPath.Trim().Length == 0) throw new ArgumentException("Recovery path is required.");
            WriteMarker(queuePath + ".corruption", "pending", destinationPath);
        }

        public void Dispose()
        {
            _connection.Dispose();
            if (_lock != null) _lock.Dispose();
        }

        public QueueItem Enqueue(string guildId, string sourcePath, string body)
        {
            return Enqueue(guildId, sourcePath, body, "attendance");
        }

        public QueueItem Enqueue(string guildId, string sourcePath, string body, string kind)
        {
            if (guildId == null || guildId.Trim().Length == 0) throw new ArgumentException("Guild is required.");
            if (body == null) throw new ArgumentException("Snapshot is required.");
            if (kind == null || kind.Trim().Length == 0) kind = "attendance";
            string hash = ReportHash.Of(body);
            string now = Stamp(DateTime.UtcNow);
            lock (_gate)
            {
                QueueItem existing = InsertOrFind(guildId, sourcePath, body, hash, now, kind);
                if (existing != null) return existing;
                existing = InsertOrFind(guildId, sourcePath, body, hash, now, kind);
                if (existing == null) throw new InvalidOperationException("Could not store the snapshot.");
                return existing;
            }
        }

        QueueItem InsertOrFind(string guildId, string sourcePath, string body, string hash, string now, string kind)
        {
            using (var tx = _connection.BeginTransaction())
            {
                QueueItem existing = Find(guildId, hash, kind, tx);
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
                item.Kind = kind;
                item.State = SyncState.Pending;
                item.Attempts = 0;
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.Transaction = tx;
                    cmd.CommandText = @"INSERT INTO items
                        (id, guild_id, body, body_hash, source_path, state, attempts, next_attempt_at, last_error, created_at, updated_at, confirmed_at, kind)
                        VALUES ($id, $guild, $body, $hash, $path, $state, 0, NULL, NULL, $now, $now, NULL, $kind)";
                    cmd.Parameters.AddWithValue("$id", item.Id);
                    cmd.Parameters.AddWithValue("$guild", item.GuildId);
                    cmd.Parameters.AddWithValue("$body", item.Body);
                    cmd.Parameters.AddWithValue("$hash", item.BodyHash);
                    cmd.Parameters.AddWithValue("$path", item.SourcePath);
                    cmd.Parameters.AddWithValue("$state", item.State);
                    cmd.Parameters.AddWithValue("$kind", item.Kind);
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

        public bool MarkSending(string id, DateTime utcNow)
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
                    if (cmd.ExecuteNonQuery() != 1)
                    {
                        tx.Rollback();
                        return false;
                    }
                    tx.Commit();
                    return true;
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
                    );";
                cmd.ExecuteNonQuery();
            }
            EnsureKind();
        }

        void EnsureKind()
        {
            bool hasKind = false;
            using (var info = _connection.CreateCommand())
            {
                info.CommandText = "PRAGMA table_info(items)";
                using (var reader = info.ExecuteReader())
                {
                    while (reader.Read())
                    {
                        if (string.Equals(reader.GetString(1), "kind", StringComparison.OrdinalIgnoreCase))
                            hasKind = true;
                    }
                }
            }
            if (!hasKind)
            {
                using (var alter = _connection.CreateCommand())
                {
                    alter.CommandText = "ALTER TABLE items ADD COLUMN kind TEXT NOT NULL DEFAULT 'attendance'";
                    alter.ExecuteNonQuery();
                }
            }
            using (var drop = _connection.CreateCommand())
            {
                drop.CommandText = "DROP INDEX IF EXISTS items_guild_hash";
                drop.ExecuteNonQuery();
            }
            using (var index = _connection.CreateCommand())
            {
                index.CommandText = "CREATE UNIQUE INDEX IF NOT EXISTS items_guild_kind_hash ON items (guild_id, kind, body_hash)";
                index.ExecuteNonQuery();
            }
        }

        QueueItem Find(string guildId, string hash, string kind, SqliteTransaction tx)
        {
            using (var cmd = _connection.CreateCommand())
            {
                cmd.Transaction = tx;
                cmd.CommandText = "SELECT * FROM items WHERE guild_id = $guild AND body_hash = $hash AND kind = $kind";
                cmd.Parameters.AddWithValue("$guild", guildId);
                cmd.Parameters.AddWithValue("$hash", hash);
                cmd.Parameters.AddWithValue("$kind", kind ?? "attendance");
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
            item.CreatedAt = Optional(reader, "created_at");
            item.UpdatedAt = Optional(reader, "updated_at");
            item.ConfirmedAt = Optional(reader, "confirmed_at");
            try
            {
                item.Kind = Optional(reader, "kind");
            }
            catch (ArgumentException)
            {
                item.Kind = "attendance";
            }
            if (item.Kind == null || item.Kind.Length == 0) item.Kind = "attendance";
            return item;
        }

        static string Optional(SqliteDataReader reader, string column)
        {
            int ordinal = reader.GetOrdinal(column);
            return reader.IsDBNull(ordinal) ? "" : reader.GetString(ordinal);
        }

        public List<QueueItem> History(int limit)
        {
            if (limit < 1) limit = 1;
            if (limit > 100) limit = 100;
            var items = new List<QueueItem>();
            lock (_gate)
            {
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.CommandText = "SELECT * FROM items ORDER BY updated_at DESC LIMIT $limit";
                    cmd.Parameters.AddWithValue("$limit", limit);
                    using (var reader = cmd.ExecuteReader())
                    {
                        while (reader.Read()) items.Add(ReadItem(reader));
                    }
                }
            }
            return items;
        }

        public string LatestError()
        {
            return Scalar("SELECT last_error FROM items ORDER BY updated_at DESC LIMIT 1");
        }

        public string LatestConfirmedAt()
        {
            return Scalar("SELECT confirmed_at FROM items WHERE confirmed_at IS NOT NULL ORDER BY confirmed_at DESC LIMIT 1");
        }

        string Scalar(string sql)
        {
            lock (_gate)
            {
                using (var cmd = _connection.CreateCommand())
                {
                    cmd.CommandText = sql;
                    object value = cmd.ExecuteScalar();
                    return value == null || value is DBNull ? "" : value.ToString();
                }
            }
        }

        static string ConnectionString(string path)
        {
            return "Data Source=" + path + ";Pooling=False";
        }

        static FileStream Acquire(string path)
        {
            try
            {
                return new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            }
            catch (IOException)
            {
                throw new InvalidOperationException("The queue is already open. Live database files were not moved.");
            }
            catch (UnauthorizedAccessException)
            {
                throw new InvalidOperationException("The queue is already open. Live database files were not moved.");
            }
        }

        static SqliteConnection OpenDatabase(string path)
        {
            var connection = new SqliteConnection(ConnectionString(path));
            connection.Open();
            using (var pragma = connection.CreateCommand())
            {
                pragma.CommandText = "PRAGMA journal_mode=WAL;";
                pragma.ExecuteNonQuery();
            }
            return connection;
        }

        static void RecoverIfNeeded(string path, out bool corrupt, out string preserved)
        {
            corrupt = false;
            preserved = "";
            string marker = path + ".corruption";
            string kind;
            string destination;
            bool markerPresent = ReadMarker(marker, out kind, out destination);
            if (markerPresent && kind == "pending")
            {
                if (destination == null || destination.Length == 0) destination = UniqueDestination(path);
                FinishPreserve(path, destination);
                WriteMarker(marker, "preserved", destination);
                corrupt = true;
                preserved = destination;
                return;
            }
            if (markerPresent) corrupt = true;
            if (destination != null && destination.Length > 0) preserved = destination;
            if (!FileSetSuspicious(path)) return;
            string dest = UniqueDestination(path);
            WriteMarker(marker, "pending", dest);
            FinishPreserve(path, dest);
            WriteMarker(marker, "preserved", dest);
            corrupt = true;
            preserved = dest;
        }

        static bool FileSetSuspicious(string path)
        {
            bool wal = File.Exists(path + "-wal");
            bool shm = File.Exists(path + "-shm");
            if (!File.Exists(path)) return wal || shm;
            long length;
            try
            {
                length = new FileInfo(path).Length;
            }
            catch (IOException)
            {
                return true;
            }
            if (length < 100) return true;
            byte[] header = new byte[100];
            try
            {
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    int read = 0;
                    while (read < header.Length)
                    {
                        int n = stream.Read(header, read, header.Length - read);
                        if (n <= 0) return true;
                        read += n;
                    }
                }
            }
            catch (IOException)
            {
                return true;
            }
            if (Encoding.ASCII.GetString(header, 0, 15) != "SQLite format 3" || header[15] != 0) return true;
            int page = (header[16] << 8) | header[17];
            if (page == 1) page = 65536;
            if (page < 512 || page > 65536 || (page & (page - 1)) != 0) return true;
            return length < page;
        }

        static string UniqueDestination(string path)
        {
            string directory = Path.GetDirectoryName(path);
            string stamp = DateTime.UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'", CultureInfo.InvariantCulture);
            string dest = Path.Combine(directory, "queue-corrupt-" + stamp + ".sqlite");
            int n = 0;
            while (File.Exists(dest) || File.Exists(dest + "-wal") || File.Exists(dest + "-shm"))
            {
                n++;
                dest = Path.Combine(directory, "queue-corrupt-" + stamp + "-" + n + ".sqlite");
            }
            return dest;
        }

        static void FinishPreserve(string path, string dest)
        {
            MoveAside(path, dest);
            MoveAside(path + "-wal", dest + "-wal");
            MoveAside(path + "-shm", dest + "-shm");
            SecureIfExists(dest);
            SecureIfExists(dest + "-wal");
            SecureIfExists(dest + "-shm");
        }

        static void MoveAside(string source, string dest)
        {
            if (!File.Exists(source) || File.Exists(dest)) return;
            string directory = Path.GetDirectoryName(dest);
            if (directory != null && directory.Length > 0) Directory.CreateDirectory(directory);
            File.Move(source, dest);
        }

        static bool ReadMarker(string marker, out string kind, out string destination)
        {
            kind = "";
            destination = "";
            if (!File.Exists(marker)) return false;
            string[] lines;
            try
            {
                lines = File.ReadAllLines(marker);
            }
            catch (IOException)
            {
                kind = "pending";
                return true;
            }
            if (lines.Length < 4 || lines[0] != "ironkeep-queue-corruption 1" || (lines[1] != "pending" && lines[1] != "preserved"))
            {
                kind = "pending";
                return true;
            }
            kind = lines[1];
            destination = lines[3];
            return true;
        }

        static void WriteMarker(string marker, string kind, string destination)
        {
            string text = "ironkeep-queue-corruption 1\n" + kind + "\n" + Stamp(DateTime.UtcNow) + "\n" + destination + "\n";
            string tmp = marker + ".tmp";
            File.WriteAllText(tmp, text, new UTF8Encoding(false));
            SecureFile(tmp);
            File.Move(tmp, marker, true);
            SecureFile(marker);
        }

        static string Stamp(DateTime utc)
        {
            return utc.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", CultureInfo.InvariantCulture);
        }

        public static void Restrict(string path)
        {
            if (path == null || path.Length == 0) return;
            if (Directory.Exists(path)) SecureDirectory(path);
            else SecureFile(path);
        }

        static void SecureDirectory(string path)
        {
            try
            {
                if (OperatingSystem.IsWindows())
                {
                    var info = new DirectoryInfo(path);
                    DirectorySecurity security = info.GetAccessControl();
                    GrantOnlyCurrentUser(security, true);
                    info.SetAccessControl(security);
                    return;
                }
                File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            }
            catch (SecurityException)
            {
                throw;
            }
            catch (Exception ex)
            {
                throw new SecurityException("The queue folder could not be limited to the current user.", ex);
            }
        }

        static void SecureIfExists(string path)
        {
            if (File.Exists(path)) SecureFile(path);
        }

        static void SecureFile(string path)
        {
            if (!File.Exists(path)) return;
            try
            {
                if (OperatingSystem.IsWindows())
                {
                    var info = new FileInfo(path);
                    FileSecurity security = info.GetAccessControl();
                    GrantOnlyCurrentUser(security, false);
                    info.SetAccessControl(security);
                    return;
                }
                File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            }
            catch (SecurityException)
            {
                throw;
            }
            catch (Exception ex)
            {
                throw new SecurityException("The queue file could not be limited to the current user: " + path, ex);
            }
        }

        static void GrantOnlyCurrentUser(FileSystemSecurity security, bool directory)
        {
            SecurityIdentifier user = WindowsIdentity.GetCurrent().User;
            if (user == null) throw new SecurityException("The current user has no Windows identity.");
            security.SetAccessRuleProtection(true, false);
            var rules = new List<FileSystemAccessRule>();
            foreach (AuthorizationRule rule in security.GetAccessRules(true, false, typeof(SecurityIdentifier)))
            {
                var access = rule as FileSystemAccessRule;
                if (access != null) rules.Add(access);
            }
            foreach (FileSystemAccessRule rule in rules)
                security.RemoveAccessRuleSpecific(rule);
            security.AddAccessRule(new FileSystemAccessRule(user, FileSystemRights.FullControl, AccessControlType.Allow));
            if (directory)
            {
                security.AddAccessRule(new FileSystemAccessRule(
                    user,
                    FileSystemRights.FullControl,
                    InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                    PropagationFlags.None,
                    AccessControlType.Allow));
            }
        }
    }
}
