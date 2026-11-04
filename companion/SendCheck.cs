using System;
using System.Collections.Generic;

namespace Ironkeep
{
    static class SendCheck
    {
        static int Main(string[] args)
        {
            if (args.Length != 4)
            {
                Console.Error.WriteLine("Usage: SendCheck <base-url> <guild> <key> <Ironkeep.lua>");
                return 2;
            }
            try
            {
                Dictionary<object, object> db = Saved.LoadPath(args[3]);
                string text = Saved.TextFor(db);
                string problem;
                Uri url = SiteClient.Target(args[0], args[1], out problem);
                if (url == null)
                {
                    Console.Error.WriteLine(problem);
                    return 2;
                }
                int status;
                string body = SiteClient.Post(url, args[2], text, out status);
                Console.WriteLine(status);
                Console.WriteLine(body);
                return status >= 200 && status < 300 && SiteClient.Accepted(body) ? 0 : 1;
            }
            catch (SavedException ex)
            {
                Console.Error.WriteLine(ex.Message);
                return 1;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine(ex.Message);
                return 1;
            }
        }
    }
}
