using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;

namespace Ironkeep.Companion
{
    public interface IStartupRegistration
    {
        void Apply(bool enabled, string name, string command);
    }

    public sealed class MemoryStartup : IStartupRegistration
    {
        public bool Enabled;
        public string Name = "";
        public string Command = "";

        public void Apply(bool enabled, string name, string command)
        {
            Enabled = enabled;
            Name = name ?? "";
            Command = command ?? "";
        }
    }

    public sealed class RegistryStartup : IStartupRegistration
    {
        public void Apply(bool enabled, string name, string command)
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Startup registration is a Windows setting.");
            using (var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", true))
            {
                if (key == null) throw new InvalidOperationException("The Windows startup key could not be opened.");
                if (enabled) key.SetValue(name, command ?? "");
                else
                {
                    try { key.DeleteValue(name, false); }
                    catch (ArgumentException) { }
                }
            }
        }
    }

    /// <summary>
    /// One companion instance per session. Windows uses a named mutex and event so a second
    /// process brings the first forward. Other platforms use an in-process stand-in for tests.
    /// </summary>
    public sealed class SingleInstance : IDisposable
    {
        static readonly object LocalGate = new object();
        static readonly Dictionary<string, LocalSlot> LocalSlots = new Dictionary<string, LocalSlot>(StringComparer.Ordinal);

        readonly Mutex _mutex;
        readonly EventWaitHandle _show;
        readonly LocalSlot _local;
        readonly string _localName;
        bool _released;

        SingleInstance(Mutex mutex, EventWaitHandle show, LocalSlot local, string localName, bool isOwner)
        {
            _mutex = mutex;
            _show = show;
            _local = local;
            _localName = localName;
            IsOwner = isOwner;
        }

        public bool IsOwner { get; private set; }

        public static SingleInstance Acquire(string name)
        {
            if (name == null || name.Trim().Length == 0) throw new ArgumentException("Instance name is required.");
            if (OperatingSystem.IsWindows()) return AcquireWindows(name);
            return AcquireLocal(name);
        }

        static SingleInstance AcquireWindows(string name)
        {
            string mutexName = @"Local\Ironkeep." + name;
            string eventName = mutexName + ".show";
            Mutex mutex = null;
            bool owner = false;
            try
            {
                mutex = new Mutex(true, mutexName, out owner);
            }
            catch (AbandonedMutexException abandoned)
            {
                mutex = abandoned.Mutex;
                owner = mutex != null;
            }
            catch (IOException)
            {
                owner = false;
            }
            var show = new EventWaitHandle(false, EventResetMode.AutoReset, eventName);
            if (!owner)
            {
                if (mutex != null) mutex.Dispose();
                return new SingleInstance(null, show, null, null, false);
            }
            return new SingleInstance(mutex, show, null, null, true);
        }

        static SingleInstance AcquireLocal(string name)
        {
            lock (LocalGate)
            {
                LocalSlot slot;
                if (!LocalSlots.TryGetValue(name, out slot))
                {
                    slot = new LocalSlot();
                    LocalSlots[name] = slot;
                }
                bool owner = slot.Owners == 0;
                if (owner) slot.Owners = 1;
                return new SingleInstance(null, null, slot, name, owner);
            }
        }

        public void Signal()
        {
            if (_show != null)
            {
                _show.Set();
                return;
            }
            lock (LocalGate) { if (_local != null) _local.Show = true; }
        }

        public bool Consume()
        {
            if (_show != null) return _show.WaitOne(0);
            lock (LocalGate)
            {
                if (_local == null || !_local.Show) return false;
                _local.Show = false;
                return true;
            }
        }

        public void Dispose()
        {
            if (_mutex != null && IsOwner && !_released)
            {
                try { _mutex.ReleaseMutex(); }
                catch (ApplicationException) { }
                _released = true;
                _mutex.Dispose();
            }
            if (_show != null) _show.Dispose();
            if (_local == null || _released) return;
            lock (LocalGate)
            {
                if (_released) return;
                _released = true;
                if (IsOwner) _local.Owners = 0;
                if (_local.Owners == 0 && !_local.Show) LocalSlots.Remove(_localName);
            }
        }

        sealed class LocalSlot
        {
            public int Owners;
            public bool Show;
        }
    }
}
